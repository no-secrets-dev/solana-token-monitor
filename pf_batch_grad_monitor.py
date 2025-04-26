import asyncio
import discord
from discord.ext import tasks
from discord.utils import get
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import MemcmpOpts
import base58
import os
from dotenv import load_dotenv
import argparse
from aiohttp import ClientError
from aiolimiter import AsyncLimiter
from tenacity import retry, stop_after_attempt, wait_exponential
import json
from solders.pubkey import Pubkey
import traceback

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CATEGORY_ID = int(os.getenv('DISCORD_CATEGORY_ID')) 
SOLANA_RPC_HTTP = os.getenv('SOL_MAINNET_HTTP_URL')
SOLANA_RPC_WSS = os.getenv('SOL_MAINNET_WSS_URL')
PUMP_PROGRAM_ID = os.getenv('PUMPFUN')
RAYDIUM_PROGRAM_ID = os.getenv('RAYDIUM')

def parse_args():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--interval", type=int, default=5,
                        help="Base interval in seconds between token status checks")
    parser.add_argument("--tokens-file", type=str, default="test_data/tokens.json",
                        help="Path to JSON file containing token addresses")
    parser.add_argument("--rpc-rate-limit", type=int, default=10,
                        help="Maximum RPC calls per second")
    parser.add_argument("--max-retries", type=int, default=5,
                        help="Maximum number of retry attempts for failed requests")
    parser.add_argument("--base-delay", type=float, default=1.0,
                        help="Base delay in seconds for exponential backoff")
    parser.add_argument("--max-delay", type=float, default=32.0,
                        help="Maximum delay in seconds for exponential backoff")
    return parser.parse_args()

class TokenMonitor(discord.Client):
    def __init__(self, check_interval: int, tokens_file: str, rpc_rate_limit: int,
                 max_retries: int, base_delay: float, max_delay: float):
        intents = discord.Intents.all()
        intents.members = True  # Explicitly enable members intent
        intents.guilds = True   # Explicitly enable guilds intent
        super().__init__(intents=intents)
        self.solana = AsyncClient(SOLANA_RPC_HTTP)
        self.base_interval = check_interval
        self.tokens_file = tokens_file
        self.rate_limiter = AsyncLimiter(rpc_rate_limit, 1)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.token_channels = {}  # Maps token addresses to their channel IDs
        self.is_ready = False

    async def on_ready(self):
        if self.is_ready:
            return

        print("Starting on_ready...")
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print(f"Bot is in {len(self.guilds)} guilds:")
        for guild in self.guilds:
            print(f"- {guild.name} (ID: {guild.id})")

        if len(self.guilds) == 0:
            raise Exception("Bot is not in any guilds!")

        print("Getting category...")
        guild = self.guilds[0]
        self.category = self.get_channel(DISCORD_CATEGORY_ID)
        if self.category is None:
            print(f"Creating new category in guild {guild.name}")
            self.category = await guild.create_category("token-statuses")

        print("Setting up token channels...")
        await self.setup_token_channels()
        print("Starting check_tokens task...")
        self.check_tokens.start()
        print("Setup complete!")
        self.is_ready = True

    def read_tokens(self) -> set:
        try:
            with open(self.tokens_file, 'r') as f:
                data = json.load(f)
                return set(data['tokens'])
        except Exception as e:
            print(f"Error reading tokens file: {e}")
            return set()

    async def setup_token_channels(self):
        tokens = self.read_tokens()
        for token in tokens:
            if f"token-{token.lower()}" not in self.token_channels:
                channel = await self.create_token_channel(token)
                self.token_channels[token] = channel.id

    async def create_token_channel(self, token: str) -> discord.TextChannel:
        channel_name = f"token-{token.lower()}"

        # Try to find existing channel first
        channel = get(self.category.channels, name=channel_name)

        if channel is None:
            # Create channel if it doesn't exist
            print (f"channel-token-{token} doesn't exist. creating...")
            channel = await self.category.guild.create_text_channel(
                channel_name,
                category=self.category,
                topic=f"Monitoring {token}"
            )

            # Create welcome embed
            embed = discord.Embed(
                title="🔍 New Token Monitor",
                description="Starting token graduation monitoring",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="Token Address", 
                value=f"[{token}](https://pump.fun/coin/{token})", 
                inline=False
            )

            embed.add_field(
                name="Status", 
                value="Monitoring for graduation progress...", 
                inline=False
            )

            embed.set_footer(text="Monitor started")

            await channel.send(embed=embed)

        else:
            print(f"found existing channel for token {token}")

        return channel

    @retry(stop=stop_after_attempt(1), wait=wait_exponential(multiplier=1, min=1, max=32))
    async def get_token_status(self, token: str) -> dict:
        async with self.rate_limiter:
            program_id = Pubkey.from_string(PUMP_PROGRAM_ID)
            token_mint = Pubkey.from_string(token)
            
            # Get PDA for bonding curve
            pda, _ = Pubkey.find_program_address(
                [
                    b"bonding-curve",
                    bytes(token_mint)
                ],
                program_id
            )
            
            resp = await self.solana.get_account_info(pda, encoding="base64")
            print ("RESPONSE:")
            print(resp)
            
            if not resp.value:
                raise ValueError(f"No data found for token {token}")
                
            data = resp.value.data
            
            try:
                # Based on BondingCurve struct:
                # discriminator: [u8; 8]     // 8 bytes
                # mint: Pubkey,             // 32 bytes
                # total_supply: u64,        // 8 bytes
                # current_supply: u64,      // 8 bytes
                # bump: u8,                 // 1 byte
                
                real_token_reserves = int.from_bytes(data[24:32], byteorder='little')
                total_supply = int.from_bytes(data[40:48], byteorder='little')
                
                DECIMALS = 1_000_000
                RESERVED_TOKENS = 206_900_000 * DECIMALS
                
                actual_total_supply = total_supply - RESERVED_TOKENS
                percentage = 100 - ((real_token_reserves * 100) / actual_total_supply)

                return {'mint': token, 'percentage': percentage}
                
            except IndexError:
                raise ValueError(f"Invalid data format for token {token}")

    # async def monitor_raydium_pools(self):
    #     async def process_logs(logs, signature):
    #         if "initialize2" in str(logs):
    #             try:
    #                 async with self.rate_limiter:
    #                     tx = await self.solana.get_parsed_transaction(signature)
    #                 for ix in tx["result"]["transaction"]["message"]["instructions"]:
    #                     if ix["programId"] == RAYDIUM_PROGRAM_ID:
    #                         accounts = ix["accounts"]
    #                         token_a = accounts[8]
    #                         token_b = accounts[9]
    #
    #                         # Send to appropriate token channels if we're monitoring either token
    #                         for token in [token_a, token_b]:
    #                             if token in self.token_channels:
    #                                 channel = self.get_channel(self.token_channels[token])
    #                                 await channel.send(
    #                                     f"🏊 New Raydium pool created!\n"
    #                                     f"Token A: {token_a}\n"
    #                                     f"Token B: {token_b}\n"
    #                                     f"Transaction: https://solscan.io/tx/{signature}"
    #                                 )
    #             except Exception as e:
    #                 print(f"Error processing pool creation: {e}")
    #
    #     # Websocket subscription - no rate limiting needed
    #     await self.solana.logs_subscribe(
    #         [{"mentions": [str(self.raydium)]}],
    #         process_logs
    #     )
    #

    # async def monitor_raydium_pools(self):
    #     async def process_logs(logs, signature):
    #         if "initialize2" in str(logs):
    #             try:
    #                 async with self.rate_limiter:
    #                     tx = await self.solana.get_parsed_transaction(signature)
    #                 for ix in tx["result"]["transaction"]["message"]["instructions"]:
    #                     if ix["programId"] == RAYDIUM_PROGRAM_ID:
    #                         accounts = ix["accounts"]
    #                         token_a = accounts[8]
    #                         token_b = accounts[9]
    #
    #                         # Send to appropriate token channels if we're monitoring either token
    #                         for token in [token_a, token_b]:
    #                             if token in self.token_channels:
    #                                 channel = self.get_channel(self.token_channels[token])
    #                                 await channel.send(
    #                                     f"🏊 New Raydium pool created!\n"
    #                                     f"Token A: {token_a}\n"
    #                                     f"Token B: {token_b}\n"
    #                                     f"Transaction: https://solscan.io/tx/{signature}"
    #                                 )
    #             except Exception as e:
    #                 print(f"Error processing pool creation: {e}")
    #
    #     # Websocket subscription - no rate limiting needed
    #     await self.solana.logs_subscribe(
    #         [{"mentions": [str(self.raydium)]}],
    #         process_logs
    #     )
    #

    @tasks.loop(seconds=5)
    async def check_tokens(self):
        try:
            print("Checking tokens...")
            tokens = self.read_tokens()

            for token in tokens:
                if f"token-{token.lower()}" not in self.token_channels:
                    channel = await self.create_token_channel(token)
                    self.token_channels[token.lower()] = channel.id
                try:
                    status = await self.get_token_status(token)
                    if status:
                        channel = self.get_channel(self.token_channels[token.lower()])

                        embed = discord.Embed(
                            title="📊 Token Status Update",
                            color=discord.Color.blue(),
                            timestamp=discord.utils.utcnow()
                        )

                        embed.add_field(
                            name="Token", 
                            value=f"[{status['mint']}](https://pump.fun/coin/{status['mint']})", 
                            inline=False
                        )

                        embed.add_field(
                            name="Graduation Progress", 
                            value=f"{status['percentage']:.2f}%", 
                            inline=False
                        )

                        await channel.send(embed=embed)

                except Exception as e:
                    print(f"Error getting status for token {token}: {e}")
                    print(traceback.format_exc())

        except Exception as e:
            print(f"Error in check_tokens: {e}")

def main():
    args = parse_args()
    client = TokenMonitor(
        check_interval=args.interval,
        tokens_file=args.tokens_file,
        rpc_rate_limit=args.rpc_rate_limit,
        max_retries=args.max_retries,
        base_delay=args.base_delay,
        max_delay=args.max_delay
    )
    print("Starting bot...")  # Add this
    try:
        client.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"Error running bot: {e}")  # Add this

if __name__ == "__main__":
    main()

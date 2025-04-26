# PumpFun Token Graduation Monitor

A Discord bot that monitors Solana tokens created on PumpFun for graduation progress.

## Overview

This script monitors the graduation status of tokens created on PumpFun. It creates Discord channels for each monitored token and posts status updates at regular intervals.

## Prerequisites

- Python 3.8+
- Discord bot token with appropriate permissions
- Solana RPC endpoints (HTTP and WSS)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/solana-token-monitor.git
cd solana-token-monitor
```

2. Install dependencies:
```bash
pip install discord.py solana aiohttp aiolimiter tenacity python-dotenv solders
```

3. Create a `.env` file with the following variables:
```
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CATEGORY_ID=your_discord_category_id
SOL_MAINNET_HTTP_URL=your_solana_mainnet_http_url
SOL_MAINNET_WSS_URL=your_solana_mainnet_wss_url
PUMPFUN=PUMPVDYcHGPCgP8YWV7WMvS2LWfnE9JFL9Qr75zXki3
RAYDIUM=675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8
```

4. Create a tokens file in JSON format (default: `test_data/tokens.json`):
```json
{
    "tokens": [
        "your_token_address_here",
        "another_token_address"
    ]
}
```

## Usage

Run the script with default settings:
```bash
python pf_batch_grad_monitor.py
```

### Command-line Options

The script accepts several command-line arguments to customize behavior:

```
--interval INTEGER       Base interval in seconds between token status checks (default: 5)
--tokens-file TEXT       Path to JSON file containing token addresses (default: test_data/tokens.json)
--rpc-rate-limit INTEGER Maximum RPC calls per second (default: 10)
--max-retries INTEGER    Maximum number of retry attempts for failed requests (default: 5)
--base-delay FLOAT       Base delay in seconds for exponential backoff (default: 1.0)
--max-delay FLOAT        Maximum delay in seconds for exponential backoff (default: 32.0)
```

Example with custom settings:
```bash
python pf_batch_grad_monitor.py --interval 10 --tokens-file test_data/example_tokens.json --rpc-rate-limit 5
```


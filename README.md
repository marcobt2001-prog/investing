# Value Investor Intelligence System

A local web application that screens, analyzes, and values publicly traded stocks using the investment principles of **Benjamin Graham** (*The Intelligent Investor*) and **Philip Fisher** (*Common Stocks and Uncommon Profits*).

## What It Does

- **Screener** - Browse 200+ curated stocks by sector, or search any US-listed company by name
- **Graham Analysis** - Scores stocks against 9 quantitative criteria from *The Intelligent Investor*
- **Fisher Checklist** - Evaluates 15 points from *Common Stocks and Uncommon Profits* (11 automated, 4 flagged for manual review)
- **Valuation Models** - Computes intrinsic value using 5 methods: Graham Formula, DCF, Book Value, Earnings Power Value, and NCAV
- **Buy/Sell Signal** - Composite valuation with recommended buy prices at 25%, 35%, and 50% margin of safety
- **Backtesting** - Simulates a Graham-style strategy over historical data with configurable parameters

## Getting an API Key

This app uses the [Financial Modeling Prep (FMP) API](https://financialmodelingprep.com/developer). The free tier allows 250 requests/day.

1. Go to https://financialmodelingprep.com/developer
2. Create a free account
3. Copy your API key from the dashboard

## Setup

### Backend (Python/Flask)

```bash
cd backend
pip install -r requirements.txt
```

### Frontend (React/Vite)

```bash
cd frontend
npm install
```

## Running

Start both servers (in separate terminals):

**Terminal 1 - Backend:**
```bash
cd backend
python app.py
```
The Flask server runs on http://localhost:5000

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```
The Vite dev server runs on http://localhost:5173

Open http://localhost:5173 in your browser, enter your FMP API key, and start analyzing stocks.

## API Usage

A full analysis uses ~6 API calls. A backtest uses ~4. The screener search uses 1. With the free tier (250/day), you can run roughly 30-35 full analyses per day.

## Disclaimer

This tool is for educational and research purposes only. It is not financial advice. Always do your own research and consult a qualified financial advisor before making investment decisions.

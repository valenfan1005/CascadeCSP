# CascadeCSP

> AI-powered US options (CSP) trading analysis with 3-tier cascading analysis, VIX regime detection, FinBERT sentiment, and a multi-agent debate system.

---

## Why CascadeCSP?

Most options sellers rely on basic screeners or gut feel. CascadeCSP takes a different approach — it synthesizes macro regime data, sector analysis, financial sentiment, and technical signals through a **3-tier cascading pipeline**, then runs a **multi-agent debate** where AI agents argue the bull and bear case before surfacing a recommendation.

You don't get a black-box score. You get the full argument.

---

## Features

**3-Tier Cascading Analysis**
Macro regime → Sector health → Individual ticker. Each tier's output constrains the next, mirroring how institutional trading desks structure their process.

**VIX Regime Detection**
Automatically classifies the current volatility environment (risk-on / risk-off / crisis) and adjusts risk parameters, strike selection guidance, and expiration preferences accordingly.

**FinBERT Sentiment Analysis**
Finance-specific NLP powered by [FinBERT](https://huggingface.co/ProsusAI/finbert) — not generic sentiment analysis. Understands that "the stock crashed through resistance" is bullish, not bearish.

**Multi-Agent Debate System**
Three AI agents with different objectives analyze every opportunity:
- **Bull Agent** — builds the strongest case for selling the put
- **Bear Agent** — identifies risks, counterarguments, and downside scenarios
- **Moderator** — synthesizes both positions and flags where disagreement is most informative

**YouTube Financial Content Analysis**
Ingests and analyzes financial YouTube content, comparing creator recommendations against the platform's own multi-agent analysis.

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/valenfan1005/CascadeCSP.git
cd CascadeCSP

# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Start the backend
chmod +x start.sh
./start.sh

# In a new terminal, start the frontend
chmod +x start-frontend.sh
./start-frontend.sh
```

The dashboard will be available at `http://localhost:3000` (or whichever port is configured).

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python |
| Frontend | JavaScript |
| Sentiment | FinBERT (HuggingFace) |
| VIX Data | Custom regime classifier |
| AI Agents | Multi-agent debate framework |

---

## Roadmap

- [ ] Alpaca broker API integration for paper trading
- [ ] Interactive Brokers (IBKR) integration
- [ ] Docker Compose for one-command setup
- [ ] Jupyter notebook demo of the analysis pipeline
- [ ] Historical backtest module
- [ ] Fourth agent: Position sizing & risk management specialist
- [ ] Real-time alerts when regime shifts are detected
- [ ] PyPI package for the analysis engine

---

## Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

Check the [Issues](https://github.com/valenfan1005/CascadeCSP/issues) tab for `good first issue` labels if you're looking for a place to start.

**Areas where help is especially welcome:**
- Broker API integrations (Alpaca, IBKR)
- Expanding the VIX regime classifier
- Adding more debate agent archetypes
- Unit tests and documentation
- Docker/containerization

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

**If CascadeCSP helps your options analysis, consider giving it a star!** It helps others discover the project.

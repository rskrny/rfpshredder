# RFP Shredder

🔥 Transform RFPs into Compliance Matrices in Minutes

## Overview

RFP Shredder is an AI-powered tool that automatically extracts binding requirements from government RFP documents and generates formatted Excel compliance matrices. What takes contractors 12-16 hours manually now takes under 10 minutes.

## Features

- **Multi-File Processing**: Upload entire solicitation packages (PDFs or ZIP files)
- **ZIP Support**: Direct upload from SAM.gov "Download All" 
- **Source Tracking**: Every requirement tagged with source document
- **Duplicate Detection**: Automatically flags duplicate requirements across files
- **Section References**: Extracts section citations (77%+ capture rate)
- **Professional Excel Output**: Formatted with dropdowns, yellow highlighting, frozen panes
- **Multiple AI Providers**: Support for Google Gemini, OpenAI, and Anthropic
- **Smart Filtering**: Optional page skip for form instructions

## Quick Start

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/rskrny/rfpshredder.git
cd rfpshredder
```

2. Create virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Create `.env` file with your API key:
```
GEMINI_API_KEY=your-api-key-here
```

4. Run the app:
```bash
streamlit run app.py
```

5. Open http://localhost:8501

## Usage

1. **Upload**: Drag and drop PDF files or ZIP file from SAM.gov
2. **Configure**: Select AI provider and strictness level (5 is recommended)
3. **Process**: Click "Shred It!" and wait for extraction
4. **Download**: Get your formatted Excel compliance matrix

## Tech Stack

- **Frontend**: Streamlit
- **PDF Parsing**: pdfplumber
- **AI**: Google Gemini (default), OpenAI, Anthropic
- **Excel Generation**: xlsxwriter, pandas
- **Data Processing**: Python 3.10+

## Pricing

- **Beta**: Free (API costs only - $2-5 per solicitation)
- **Production**: $500-2000 per solicitation or subscription plans

## ROI

- **Manual effort**: 12-16 hours per solicitation package
- **RFP Shredder**: 8-10 minutes
- **Time savings**: 95%+

## Requirements

See `requirements.txt` for full dependencies.

## License

Proprietary - All Rights Reserved

## Contact

For beta access or enterprise pricing: [Contact Info]

---

Built for government contractors who value their time.

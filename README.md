# LedgerLens — Financial Intelligence Platform

LedgerLens is a deployed AI-powered financial document intelligence platform that helps users analyze business PDFs and generate structured due diligence reports using Retrieval-Augmented Generation (RAG).

## Live Demo

Live App: https://sharvarid01-ledgerlens.hf.space
GitHub: https://github.com/Sharvarid03/LedgerLens

## What It Does

LedgerLens allows users to upload business documents such as annual reports, audit reports, balance sheets, and investor documents. It extracts text from PDFs, creates embeddings, retrieves relevant evidence using FAISS, and generates professional reports using an LLM.

The platform supports project-based uploads, user workspaces, source-backed insights, report history, editable saved reports, and downloadable PDF/TXT reports.

## Key Features

* User signup, login, logout, and password hashing
* Personal workspace for each user
* Project-based PDF uploads
* Multi-document financial analysis
* RAG-based report generation
* Source-backed insights with document/page references
* Multiple report types: Due Diligence, Financial Health, Investment Memo, Compliance Review, Risk Assessment, Custom Analysis
* Saved report history
* Editable saved reports
* PDF/TXT report download
* Review and rating system
* Hidden admin backend
* Pricing plan logic for Free, Pro, and Enterprise plans

## Tech Stack

* Python
* Streamlit
* FAISS
* sentence-transformers
* Groq LLM
* SQLite
* pypdf
* ReportLab
* Hugging Face Spaces
* GitHub

## How It Works

```text
User Login
↓
Create Project
↓
Upload Financial PDFs
↓
Extract and Chunk Text
↓
Generate Embeddings
↓
Retrieve Evidence using FAISS
↓
Generate Structured Report using LLM
↓
Save Report in Workspace
↓
Edit / Download Report
```

## Why It Is Different From a Normal PDF Chatbot

A regular PDF chatbot usually gives short answers to user questions. LedgerLens is designed as a financial workflow platform. It organizes documents into projects, retrieves source-backed evidence, generates structured business reports, saves report history, and allows users to edit and download professional reports.

## Use Cases

* Financial due diligence
* Investment research
* Risk assessment
* Compliance review
* Business document analysis
* Analyst memo preparation
* Internal company report review

## Limitations

* Public demo should be used only with public or non-confidential documents.
* Long reports depend on LLM token limits.
* Email delivery and payment gateway are planned future enhancements.
* SQLite is used for MVP; production version should use PostgreSQL or Supabase.

## Author

Sharvari Nilesh Dhekre
Information Technology Undergraduate
Email: [sharvaridhekre05@gmail.com](mailto:sharvaridhekre05@gmail.com)
LinkedIn: https://linkedin.com/in/sharvari-dhekre

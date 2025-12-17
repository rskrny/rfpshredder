"""
RFP Shredder - Compliance Matrix Generator
A Streamlit app that extracts binding requirements from PDF RFPs using AI
and generates formatted Excel compliance matrices.
"""

import streamlit as st
import pdfplumber
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Alignment
from openpyxl.worksheet.datavalidation import DataValidation
import json
import io
import re
import os
import zipfile
from typing import List, Dict, Optional
from datetime import datetime
from dotenv import load_dotenv
from docx import Document

# Load environment variables from .env file
load_dotenv()


# ============================================================================
# CONFIGURATION
# ============================================================================

# Keywords to filter pages before sending to LLM (cost optimization)
REQUIREMENT_KEYWORDS = ["shall", "must", "will", "required", "submit"]

# LLM Provider configurations
LLM_PROVIDERS = {
    "Google Gemini 2.5 Flash (Recommended)": {
        "provider": "gemini",
        "model": "models/gemini-2.5-flash",
        "env_var": "GEMINI_API_KEY"
    },
    "Google Gemini 2.0 Flash": {
        "provider": "gemini",
        "model": "models/gemini-2.0-flash",
        "env_var": "GEMINI_API_KEY"
    },
    "Google Gemini Pro Latest": {
        "provider": "gemini",
        "model": "models/gemini-pro-latest",
        "env_var": "GEMINI_API_KEY"
    },
    "OpenAI (gpt-4o-mini)": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "env_var": "OPENAI_API_KEY"
    },
    "Anthropic (claude-3-haiku)": {
        "provider": "anthropic",
        "model": "claude-3-haiku-20240307",
        "env_var": "ANTHROPIC_API_KEY"
    }
}


# ============================================================================
# PDF PROCESSING CLASS
# ============================================================================

class PDFProcessor:
    """
    Handles PDF file reading and text extraction with optimization filters.
    """
    
    def __init__(self, file_bytes: bytes):
        """
        Initialize the PDF processor with file bytes.
        
        Args:
            file_bytes: Raw bytes of the PDF file
        """
        self.file_bytes = file_bytes
        
    def extract_text_by_page(self) -> List[Dict[str, any]]:
        """
        Extract text from each page of the PDF with keyword filtering.
        
        Returns:
            List of dictionaries with page number, text, and processing flag
            Format: [{'page': 1, 'text': '...', 'should_process': True}]
        """
        pages_data = []
        
        try:
            # Open PDF from bytes
            with pdfplumber.open(io.BytesIO(self.file_bytes)) as pdf:
                total_pages = len(pdf.pages)
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    # Extract text from the page
                    text = page.extract_text()
                    
                    if not text:
                        pages_data.append({
                            'page': page_num,
                            'text': '',
                            'should_process': False,
                            'skip_reason': 'Empty page'
                        })
                        continue
                    
                    # Keyword Filter: Check if page contains requirement keywords
                    text_lower = text.lower()
                    has_keywords = any(keyword in text_lower for keyword in REQUIREMENT_KEYWORDS)
                    
                    pages_data.append({
                        'page': page_num,
                        'text': text,
                        'should_process': has_keywords,
                        'skip_reason': None if has_keywords else 'No requirement keywords found'
                    })
                    
        except Exception as e:
            raise Exception(f"PDF Processing Error: {str(e)}")
            
        return pages_data


# ============================================================================
# DOCX PROCESSING CLASS
# ============================================================================

class DocxProcessor:
    """
    Handles DOCX file reading and text extraction with optimization filters.
    """
    
    def __init__(self, file_bytes: bytes):
        """
        Initialize the DOCX processor with file bytes.
        
        Args:
            file_bytes: Raw bytes of the DOCX file
        """
        self.file_bytes = file_bytes
        
    def extract_text_by_page(self) -> List[Dict[str, any]]:
        """
        Extract text from DOCX file. Since Word doesn't have pages like PDF,
        we treat each section/paragraph group as a "page".
        
        Returns:
            List of dictionaries with page number, text, and processing flag
        """
        pages_data = []
        
        try:
            # Open DOCX from bytes
            doc = Document(io.BytesIO(self.file_bytes))
            
            # Group paragraphs into chunks (simulate pages)
            chunk_size = 10  # paragraphs per chunk
            current_chunk = []
            chunk_num = 1
            
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:  # Skip empty paragraphs
                    current_chunk.append(text)
                    
                    if len(current_chunk) >= chunk_size:
                        # Process chunk
                        chunk_text = '\n'.join(current_chunk)
                        text_lower = chunk_text.lower()
                        has_keywords = any(keyword in text_lower for keyword in REQUIREMENT_KEYWORDS)
                        
                        pages_data.append({
                            'page': chunk_num,
                            'text': chunk_text,
                            'should_process': has_keywords,
                            'skip_reason': None if has_keywords else 'No requirement keywords found'
                        })
                        
                        current_chunk = []
                        chunk_num += 1
            
            # Process remaining paragraphs
            if current_chunk:
                chunk_text = '\n'.join(current_chunk)
                text_lower = chunk_text.lower()
                has_keywords = any(keyword in text_lower for keyword in REQUIREMENT_KEYWORDS)
                
                pages_data.append({
                    'page': chunk_num,
                    'text': chunk_text,
                    'should_process': has_keywords,
                    'skip_reason': None if has_keywords else 'No requirement keywords found'
                })
                    
        except Exception as e:
            raise Exception(f"DOCX Processing Error: {str(e)}")
            
        return pages_data


# ============================================================================
# REQUIREMENT EXTRACTION CLASS
# ============================================================================

class RequirementExtractor:
    """
    Uses LLM to extract binding requirements from text.
    """
    
    def __init__(self, api_key: str, provider: str = "openai", model: str = "gpt-4o-mini", strictness: int = 5):
        """
        Initialize the requirement extractor with API credentials.
        
        Args:
            api_key: API key for the LLM provider
            provider: 'openai' or 'anthropic'
            model: Model name to use
            strictness: Level 1-10 controlling extraction sensitivity
        """
        self.api_key = api_key
        self.provider = provider
        self.model = model
        self.strictness = strictness
        
        # Initialize the appropriate client
        if provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        elif provider == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.client = genai.GenerativeModel(model)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    
    def _build_system_prompt(self) -> str:
        """
        Build the system prompt based on strictness level.
        
        Returns:
            System prompt string
        """
        strictness_guidance = {
            1: "Only extract requirements with explicit 'SHALL' or 'MUST' in all caps.",
            2: "Extract requirements with 'shall' or 'must' (case insensitive).",
            3: "Extract requirements with 'shall', 'must', or strong 'will' statements.",
            4: "Extract all 'shall', 'must', 'will' requirements and clear obligations.",
            5: "Extract binding requirements including 'shall', 'must', 'will', 'required'.",
            6: "Extract all requirements including implied obligations.",
            7: "Extract requirements and strongly worded recommendations.",
            8: "Extract all requirements, recommendations, and conditional obligations.",
            9: "Extract any statement that could be interpreted as a requirement.",
            10: "Extract all actionable statements, requirements, and guidance."
        }
        
        guidance = strictness_guidance.get(self.strictness, strictness_guidance[5])
        
        return f"""You are a precise legal auditor specializing in government contract requirements.

Your task: {guidance}

RULES:
1. Extract complete sentences or clauses containing binding obligations
2. CRITICAL: Capture section references in ANY of these formats:
   - "Section 3.2" / "Sec. 4.1" / "§5.3"
   - "Paragraph 2.1" / "Para 3.4" / "Para. C"
   - "Clause 52.219-9" / "FAR 52.212-4"
   - "Article V" / "Part III"
   - "Subsection A.2" / "Sub-para 1.2.3"
   - If mentioned ANYWHERE near the requirement, extract it
3. Ignore: definitions, questions, background information, page headers/footers
4. DO NOT extract form-filling instructions (e.g., "Complete Block 12", "Sign and return")
5. Classify sensitivity:
   - HIGH: Mandatory compliance (shall, must, required to)
   - MEDIUM: Strong expectation (will, expected to, agrees to)
   - LOW: Recommendation (should, may, encouraged to)

Return ONLY valid JSON in this exact format:
{{
    "requirements": [
        {{
            "requirement_text": "The complete requirement sentence",
            "section_reference": "Section X.Y or null if not found",
            "sensitivity": "HIGH or MEDIUM or LOW"
        }}
    ]
}}

If no requirements found, return: {{"requirements": []}}"""

    def process_page(self, text: str, page_num: int) -> List[Dict[str, any]]:
        """
        Send page text to LLM and extract requirements.
        
        Args:
            text: Page text to process
            page_num: Page number for reference
            
        Returns:
            List of requirement dictionaries
        """
        try:
            system_prompt = self._build_system_prompt()
            user_prompt = f"Extract requirements from this RFP page:\n\n{text}"
            
            # Call appropriate LLM
            if self.provider == "openai":
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                content = response.choices[0].message.content
                
            elif self.provider == "anthropic":
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_prompt}
                    ]
                )
                content = response.content[0].text
                
            elif self.provider == "gemini":
                full_prompt = f"{system_prompt}\n\n{user_prompt}"
                response = self.client.generate_content(
                    full_prompt,
                    generation_config={
                        "temperature": 0.1,
                        "response_mime_type": "application/json"
                    }
                )
                content = response.text
            
            # Parse JSON response
            result = json.loads(content)
            requirements = result.get("requirements", [])
            
            # Add page number to each requirement
            for req in requirements:
                req['page'] = page_num
                
            return requirements
            
        except json.JSONDecodeError as e:
            st.warning(f"⚠️ Page {page_num}: LLM returned invalid JSON. Skipping.")
            return []
        except Exception as e:
            st.error(f"❌ Page {page_num}: Error - {str(e)}")
            return []


# ============================================================================
# EXCEL FORMATTING - Using xlsxwriter for reliable formatting
# ============================================================================

def format_excel_output(df: pd.DataFrame, output_path: str) -> bytes:
    """
    Format the Excel file with proper styling and validation using xlsxwriter.
    
    Args:
        df: DataFrame with requirements
        output_path: In-memory bytes buffer
        
    Returns:
        Formatted Excel file as bytes
    """
    # Create Excel file with xlsxwriter engine
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Compliance Matrix', index=False)
        
        # Get workbook and worksheet objects
        workbook = writer.book
        worksheet = writer.sheets['Compliance Matrix']
        
        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1
        })
        
        yellow_format = workbook.add_format({
            'bg_color': '#FFFF00',
            'text_wrap': True,
            'valign': 'top',
            'border': 1
        })
        
        text_wrap_format = workbook.add_format({
            'text_wrap': True,
            'valign': 'top',
            'border': 1
        })
        
        center_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })
        
        # Set column widths
        worksheet.set_column('A:A', 10)   # ID
        worksheet.set_column('B:B', 30)   # Source Document
        worksheet.set_column('C:C', 8)    # Page
        worksheet.set_column('D:D', 50)   # Requirement Text
        worksheet.set_column('E:E', 35)   # Compliance Response (YELLOW)
        worksheet.set_column('F:F', 12)   # Compliant?
        worksheet.set_column('G:G', 12)   # Sensitivity
        worksheet.set_column('H:H', 10)   # Duplicate?
        
        # Format header row
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        # Format data rows
        num_rows = len(df)
        for row_num in range(num_rows):
            # Column A: ID
            worksheet.write(row_num + 1, 0, df.iloc[row_num, 0], center_format)
            
            # Column B: Source Document (wrap text)
            worksheet.write(row_num + 1, 1, df.iloc[row_num, 1], text_wrap_format)
            
            # Column C: Page (center)
            worksheet.write(row_num + 1, 2, df.iloc[row_num, 2], center_format)
            
            # Column D: Requirement Text (wrap text)
            worksheet.write(row_num + 1, 3, df.iloc[row_num, 3], text_wrap_format)
            
            # Column E: Compliance Response (YELLOW + wrap text)
            worksheet.write(row_num + 1, 4, df.iloc[row_num, 4], yellow_format)
            
            # Column F: Compliant? (center)
            worksheet.write(row_num + 1, 5, df.iloc[row_num, 5], center_format)
            
            # Column G: Sensitivity (center)
            worksheet.write(row_num + 1, 6, df.iloc[row_num, 6], center_format)
            
            # Column H: Duplicate? (center)
            worksheet.write(row_num + 1, 7, df.iloc[row_num, 7], center_format)
        
        # Add dropdown validation for "Compliant?" column (F)
        worksheet.data_validation(f'F2:F{num_rows + 1}', {
            'validate': 'list',
            'source': ['Yes', 'No', 'Partial', 'N/A'],
            'input_message': 'Select compliance status',
            'error_message': 'Please select from the dropdown'
        })
        
        # Freeze header row
        worksheet.freeze_panes(1, 0)
    
    # Return bytes
    output_path.seek(0)
    return output_path.read()


# ============================================================================
# MAIN STREAMLIT APP
# ============================================================================

def main():
    """
    Main Streamlit application logic.
    """
    # Page configuration
    st.set_page_config(
        page_title="RFP Shredder",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Title and description
    st.title("📄 RFP Shredder")
    st.markdown("**Transform RFPs into Compliance Matrices in Minutes**")
    st.markdown("---")
    
    # Privacy badge
    st.info("🔒 **Privacy First**: All files processed in-memory. Supports PDF, Word (.docx), and ZIP files. No data is saved.")
    
    # ========================================================================
    # SIDEBAR CONFIGURATION
    # ========================================================================
    
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Auto-configure AI provider from environment (hidden from user)
        provider_choice = "Google Gemini 2.5 Flash (Recommended)"
        provider_config = LLM_PROVIDERS[provider_choice]
        
        # Load API key from environment (required for deployment)
        api_key = os.getenv(provider_config['env_var'])
        
        if not api_key:
            st.error("⚠️ Service configuration error. Please contact support.")
            st.stop()
        
        # Strictness Level
        st.subheader("1. Extraction Strictness")
        strictness = st.slider(
            "Strictness Level",
            min_value=1,
            max_value=10,
            value=5,
            help="1 = Only explicit SHALL/MUST | 10 = Extract all actionable statements"
        )
        
        # Display strictness description
        strictness_desc = {
            1: "Ultra-strict (SHALL/MUST only)",
            2: "Very strict",
            3: "Strict",
            4: "Moderately strict",
            5: "**Balanced** (Recommended)",
            6: "Moderate",
            7: "Inclusive",
            8: "Very inclusive",
            9: "Ultra-inclusive",
            10: "Maximum capture"
        }
        st.caption(f"Mode: {strictness_desc.get(strictness, 'Balanced')}")
        
        # Page Skip Filter
        st.subheader("2. Page Filter")
        skip_first_pages = st.number_input(
            "Skip first N pages",
            min_value=0,
            max_value=10,
            value=0,
            help="Optional: Skip cover pages if they contain form instructions. Test with 0 first."
        )
        if skip_first_pages > 0:
            st.caption(f"⚠️ Processing will start from page {skip_first_pages + 1}")
        
        st.markdown("---")
        st.caption("💡 **Tip**: Start with level 5 and adjust based on results")
    
    # ========================================================================
    # MAIN AREA
    # ========================================================================
    
    # File uploader
    st.header("📤 Upload RFP Documents")
    uploaded_files = st.file_uploader(
        "Choose file(s) or ZIP file",
        type=['pdf', 'docx', 'doc', 'zip'],
        accept_multiple_files=True,
        help="Upload PDFs, Word documents (.docx), or ZIP file from SAM.gov 'Download All'"
    )
    
    # Process uploaded files (handle ZIP extraction)
    doc_files = []
    if uploaded_files:
        for uploaded_file in uploaded_files:
            if uploaded_file.name.endswith('.zip'):
                # Extract PDFs from ZIP
                st.info(f"🗂️ Extracting {uploaded_file.name}...")
                try:
                    with zipfile.ZipFile(io.BytesIO(uploaded_file.read())) as zip_ref:
                        # Get all PDF and DOCX files from the zip
                        doc_names = [name for name in zip_ref.namelist() 
                                   if (name.lower().endswith(('.pdf', '.docx', '.doc')) 
                                       and not name.startswith('__MACOSX'))]
                        
                        for pdf_name in doc_names:
                            pdf_bytes = zip_ref.read(pdf_name)
                            # Create a proper file-like object with BytesIO
                            class DocumentFile:
                                def __init__(self, name, data):
                                    self.name = os.path.basename(name)
                                    self.data = data
                                    self.size = len(data)
                                    self._io = None
                                
                                def read(self):
                                    if self._io is None:
                                        self._io = io.BytesIO(self.data)
                                    return self._io.getvalue()
                            
                            doc_files.append(DocumentFile(pdf_name, pdf_bytes))
                        
                        st.success(f"✅ Extracted {len(doc_names)} document(s) from {uploaded_file.name}")
                except Exception as e:
                    st.error(f"❌ Failed to extract {uploaded_file.name}: {str(e)}")
            else:
                # Regular PDF file
                pdf_files.append(uploaded_file)
        
        if pdf_files:
            st.success(f"📚 Ready to process: {len(pdf_files)} PDF file(s)")
            with st.expander("View files"):
                for f in pdf_files:
                    st.text(f"• {f.name}")
    
    # Process button
    if doc_files:
        # Shred It button
        if st.button("🔥 **Shred It!**", type="primary", use_container_width=True):
            
            # Initialize containers
            progress_container = st.empty()
            status_container = st.empty()
            
            try:
                # ============================================================
                # STEP 1: MULTI-FILE PDF EXTRACTION
                # ============================================================
                
                status_container.info(f"📖 Step 1/3: Reading {len(doc_files)} document(s)...")
                
                all_requirements = []
                
                # Process each document file
                for file_idx, uploaded_file in enumerate(doc_files, start=1):
                    st.write(f"---\n**Processing: {uploaded_file.name}** ({file_idx}/{len(doc_files)})")
                    
                    # Read file bytes
                    file_bytes = uploaded_file.read()
                    
                    # Initialize appropriate processor based on file type
                    if uploaded_file.name.lower().endswith(('.docx', '.doc')):
                        processor = DocxProcessor(file_bytes)
                    else:
                        processor = PDFProcessor(file_bytes)
                    
                    # Extract text by page
                    pages_data = processor.extract_text_by_page()
                    total_pages = len(pages_data)
                    
                    # Apply page skip filter
                    pages_after_skip = [p for p in pages_data if p['page'] > skip_first_pages]
                    pages_to_process = [p for p in pages_after_skip if p['should_process']]
                    
                    # Info message about skipped pages
                    if skip_first_pages > 0:
                        st.caption(f"ℹ️ Skipped first {skip_first_pages} pages")
                    
                    st.caption(f"📄 {total_pages} pages | {len(pages_to_process)} pages with requirement keywords")
                    
                    if len(pages_to_process) == 0:
                        st.warning(f"⚠️ No requirements found in {uploaded_file.name}")
                        continue
                    
                    # ============================================================
                    # STEP 2: LLM EXTRACTION (per file)
                    # ============================================================
                    
                    # Initialize extractor
                    extractor = RequirementExtractor(
                        api_key=api_key,
                        provider=provider_config['provider'],
                        model=provider_config['model'],
                        strictness=strictness
                    )
                    
                    # Process each page
                    file_requirements = []
                    progress_bar = st.progress(0)
                    
                    for idx, page_data in enumerate(pages_to_process, start=1):
                        # Update progress
                        progress = idx / len(pages_to_process)
                        progress_bar.progress(progress)
                        progress_container.text(f"[{uploaded_file.name}] Scanning page {page_data['page']}... ({idx}/{len(pages_to_process)})")
                        
                        # Extract requirements
                        requirements = extractor.process_page(page_data['text'], page_data['page'])
                        
                        # Add source file to each requirement
                        for req in requirements:
                            req['source_file'] = uploaded_file.name
                        
                        file_requirements.extend(requirements)
                    
                    progress_bar.progress(1.0)
                    st.success(f"✅ {len(file_requirements)} requirements extracted from {uploaded_file.name}")
                    all_requirements.extend(file_requirements)
                
                # Check if any requirements found across all files
                status_container.success(f"✅ Total extraction: {len(all_requirements)} requirements from {len(doc_files)} file(s)")
                
                if len(all_requirements) == 0:
                    st.warning("⚠️ No requirements extracted from any files. Try adjusting the strictness level.")
                    return
                
                # ============================================================
                # STEP 3: GENERATE EXCEL WITH DEDUPLICATION
                # ============================================================
                
                status_container.info("📊 Step 3/3: Generating compliance matrix...")
                
                # Create DataFrame
                df = pd.DataFrame(all_requirements)
                
                # Add ID column
                df.insert(0, 'ID', [f"R-{str(i+1).zfill(3)}" for i in range(len(df))])
                
                # Detect duplicates
                df['is_duplicate'] = df.duplicated(subset=['requirement_text'], keep='first')
                duplicate_count = df['is_duplicate'].sum()
                
                # Reorder columns
                df = df[['ID', 'source_file', 'page', 'requirement_text', 'section_reference', 'sensitivity', 'is_duplicate']]
                df.columns = ['ID', 'Source Document', 'Page #', 'Requirement Text', 'Section Reference', 'Sensitivity', 'Duplicate?']
                
                # Mark duplicates
                df['Duplicate?'] = df['Duplicate?'].apply(lambda x: 'YES' if x else '')
                
                # Add empty columns for user input
                df.insert(5, 'Compliance Response', '')
                df.insert(6, 'Compliant?', '')
                
                # Show duplicate warning if found
                if duplicate_count > 0:
                    st.warning(f"⚠️ Found {duplicate_count} duplicate requirement(s) across files. Marked in 'Duplicate?' column.")
                
                # Display preview
                st.subheader("📋 Preview (First 5 Requirements)")
                st.dataframe(df.head(5), use_container_width=True)
                
                # Display statistics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Requirements", len(df))
                with col2:
                    high_count = len(df[df['Sensitivity'] == 'HIGH'])
                    st.metric("High Priority", high_count)
                with col3:
                    pages_with_reqs = df['Page #'].nunique()
                    st.metric("Pages with Reqs", pages_with_reqs)
                
                # ============================================================
                # STEP 4: DOWNLOAD BUTTON
                # ============================================================
                
                # Format Excel
                output = io.BytesIO()
                excel_bytes = format_excel_output(df, output)
                
                # Generate filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"compliance_matrix_{timestamp}.xlsx"
                
                # Download button
                st.download_button(
                    label="⬇️ Download Compliance Matrix (.xlsx)",
                    data=excel_bytes,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary"
                )
                
                status_container.success("✅ All done! Download your compliance matrix above.")
                
            except Exception as e:
                st.error(f"❌ An error occurred: {str(e)}")
                st.exception(e)
    
    else:
        # Instructions when no file is uploaded
        st.info("👆 Upload your RFP documents to get started")
        
        with st.expander("📖 How to Use"):
            st.markdown("""
            1. **Upload** your RFP documents:
               - Single or multiple PDFs
               - Word documents (.docx)
               - ZIP file from SAM.gov "Download All"
            2. **Adjust** settings if needed:
               - Extraction strictness (5 is recommended)
               - Page filter (optional, skip cover pages)
            3. **Click** "Shred It!" to process
            4. **Review** the preview and download your Excel compliance matrix
            
            **What you'll get:**
            - ✅ Extracted requirements with page/section references
            - ✅ Source document tracking (for multi-file uploads)
            - ✅ Duplicate detection across documents
            - ✅ Sensitivity classification (High/Medium/Low)
            - ✅ Professional Excel with dropdowns and formatting
            """)
        
        with st.expander("⚡ Features"):
            st.markdown("""
            **Intelligent Processing:**
            - 🗂️ **ZIP support**: Upload entire SAM.gov packages
            - 📄 **Multi-format**: PDF and Word documents
            - 🎯 **Smart filtering**: Skips pages without requirement keywords
            - 🔍 **Duplicate detection**: Flags repeated requirements
            - 📊 **Source tracking**: Know which document each requirement came from
            
            **Time Savings:**
            - Manual effort: 12-16 hours per solicitation
            - RFP Shredder: 8-10 minutes
            - **You save 95%+ of your time**
            """)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()

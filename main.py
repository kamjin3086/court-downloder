import os
import re
import logging
import zipfile # Added for ZIP functionality
import io        # Added for in-memory file handling
from fastapi import FastAPI, Request, Form, HTTPException, Body # Added Body
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse # Added StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
# Remove Playwright, keep BeautifulSoup potentially for fallback or future use if needed
# from playwright.async_api import async_playwright 
from bs4 import BeautifulSoup
import asyncio
import httpx
from urllib.parse import urlparse, parse_qs, quote
from pydantic import BaseModel # For request body validation

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- FastAPI App Setup ---
app = FastAPI(title="法院文书下载器")
templates = Jinja2Templates(directory="templates")

# --- Constants ---
COURT_URL_PATTERN = r"(https?://zxfw\.court\.gov\.cn/[^\s]+)"
# API Endpoint identified from cURL
API_ENDPOINT_URL = "https://zxfw.court.gov.cn/yzw/yzw-zxfw-sdfw/api/v1/sdfw/getWsListBySdbhNew"
# Mimic browser headers from cURL, initially excluding Cookie
API_HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json', # Crucial for POST
    'DNT': '1',
    'Origin': 'https://zxfw.court.gov.cn',
    'Referer': 'https://zxfw.court.gov.cn/zxfw/', # Important header
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"'
    # 'Cookie': 'acw_tc=...' # Excluded for now, add if needed
}

# --- Pydantic Models --- (For Request Body Validation)
class DownloadParams(BaseModel):
    sdbh: str
    qdbh: str
    sdsin: str

# --- Helper Functions ---
def extract_url_params(url: str) -> dict | None:
    """Extracts sdbh, qdbh, sdsin from the court URL query parameters."""
    try:
        parsed_url = urlparse(url)
        # Query params might be in the fragment (#) part for SPA URLs
        query_part = parsed_url.query if parsed_url.query else parsed_url.fragment
        if '?' in query_part: # Handle cases where fragment also contains path before query
             query_part = query_part.split('?', 1)[1]
             
        params = parse_qs(query_part)
        sdbh = params.get('sdbh', [None])[0]
        qdbh = params.get('qdbh', [None])[0]
        sdsin = params.get('sdsin', [None])[0]

        if sdbh and qdbh and sdsin:
            logger.info(f"Extracted params: sdbh={sdbh}, qdbh={qdbh}, sdsin={sdsin}")
            return {"sdbh": sdbh, "qdbh": qdbh, "sdsin": sdsin}
        else:
            logger.warning(f"Could not extract all required parameters from URL: {url}")
            logger.warning(f"Parsed params: sdbh={sdbh}, qdbh={qdbh}, sdsin={sdsin}")
            return None
    except Exception as e:
        logger.error(f"Error parsing URL parameters from {url}: {e}", exc_info=True)
        return None

async def fetch_documents_via_api(params: dict) -> list[dict]:
    """Fetches document list by calling the court's API endpoint."""
    documents = []
    payload = {
        "sdbh": params.get("sdbh"),
        "qdbh": params.get("qdbh"),
        "sdsin": params.get("sdsin")
    }
    logger.info(f"(fetch_documents_via_api) Calling API: {API_ENDPOINT_URL} with payload: {payload}")

    try:
        async with httpx.AsyncClient(headers=API_HEADERS, timeout=30.0) as client:
            response = await client.post(API_ENDPOINT_URL, json=payload) # Send data as JSON

            logger.info(f"(fetch_documents_via_api) API response status code: {response.status_code}")
            # logger.debug(f"API response headers: {response.headers}")
            
            response.raise_for_status() 

            api_data = response.json()
            # logger.debug(f"API response data: {api_data}") 

            # --- Process the API response based on the provided structure ---
            if isinstance(api_data, dict) and api_data.get('code') == 200 and 'data' in api_data and isinstance(api_data['data'], list):
                raw_docs = api_data['data']
                logger.info(f"(fetch_documents_via_api) Found {len(raw_docs)} documents in API response 'data' list.")

                for doc in raw_docs:
                    if isinstance(doc, dict):
                        # Extract name and URL using the correct keys
                        name = doc.get('c_wsmc')
                        url = doc.get('wjlj')
                        
                        if name and url:
                            logger.info(f"(fetch_documents_via_api) Extracted from API: Name='{name}', URL='{url}'")
                            documents.append({"name": name, "url": url})
                        else:
                            logger.warning(f"(fetch_documents_via_api) Skipping document entry due to missing 'c_wsmc' or 'wjlj': {doc}")
                    else:
                        logger.warning(f"(fetch_documents_via_api) Skipping non-dict item in document list: {doc}")
                
                if not documents and len(raw_docs) > 0:
                     logger.warning("(fetch_documents_via_api) Found items in 'data' list but failed to extract name/url from any.")

            else:
                # Log error if structure is not as expected
                logger.error(f"(fetch_documents_via_api) Unexpected API response format or error code. Code: {api_data.get('code')}, Msg: {api_data.get('msg')}. Expected dict with code 200 and a 'data' list.")
                # You might want to raise an exception or return empty list depending on desired behavior

            if not documents:
                 logger.warning("(fetch_documents_via_api) No documents extracted. This might happen if the 'data' list was empty or parsing failed.")

    except httpx.HTTPStatusError as e:
        response_text = "(Could not decode response text)"
        try:
            response_text = await e.response.text()
        except Exception as decode_err:
            logger.error(f"(fetch_documents_via_api) Failed to decode error response text: {decode_err}")
            
        logger.error(f"(fetch_documents_via_api) API call failed with status {e.response.status_code}. URL: {e.request.url}. Response: {response_text[:500]}...", exc_info=False) 
        error_detail = f"无法获取文书列表（服务器状态码: {e.response.status_code}）。请检查链接或稍后再试。"
        if e.response.status_code == 403:
             error_detail += " (可能是访问权限或 Cookie 问题)"
        elif e.response.status_code == 401:
             error_detail += " (可能是需要登录或授权)"
        raise HTTPException(status_code=e.response.status_code, detail=error_detail)

    except httpx.RequestError as e:
        logger.error(f"Error during API request to {API_ENDPOINT_URL}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"请求法院 API 时出错: {e}")
    except Exception as e: 
        logger.error(f"Error processing API response from {API_ENDPOINT_URL}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理 API 响应时发生错误: {e}")

    return documents

# --- API Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the main HTML page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/get_documents", response_class=JSONResponse)
async def get_documents(request: Request, sms_content: str = Form(...)):
    """Receives SMS content, extracts URL params, calls API, returns document list."""
    logger.info(f"Received request with SMS content: {sms_content[:100]}...") # Log more content
    
    # First, find the URL in the text
    url_match = re.search(COURT_URL_PATTERN, sms_content)
    if not url_match:
         logger.warning("No valid court URL found in the input text using regex.")
         raise HTTPException(status_code=400, detail="未在输入内容中找到有效的法院链接。")
         
    extracted_url = url_match.group(0)
    logger.info(f"Found URL: {extracted_url}")

    # Then, parse parameters from the found URL
    params = extract_url_params(extracted_url)
    if not params:
        logger.error(f"Failed to extract required sdbh/qdbh/sdsin parameters from URL: {extracted_url}")
        raise HTTPException(status_code=400, detail="无法从链接中解析出必要的参数 (sdbh, qdbh, sdsin)。请确保链接完整。")

    logger.info(f"Calling API with extracted parameters...")
    try:
        # Call the new API fetching function
        documents = await fetch_documents_via_api(params) 
        logger.info(f"Successfully retrieved {len(documents)} documents via API.")
        return {"documents": documents}
    except HTTPException as http_exc:
        # Re-raise HTTP exceptions directly (already logged in fetch_documents_via_api)
        raise http_exc
    except Exception as e:
        # Log any other unexpected errors during the process
        logger.error(f"Unhandled error during document retrieval process: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理请求时发生内部错误: {e}")

@app.post("/download_all")
async def download_all(params: DownloadParams = Body(...)):
    """Fetches documents, downloads them, zips them, and returns the zip file."""
    logger.info(f"Received request for /download_all with params: {params}")
    
    try:
        # 1. Fetch the document list again using the provided params
        # This ensures we potentially get fresh signed URLs if they expire quickly
        logger.info(f"Calling API with extracted parameters for download...")
        documents = await fetch_documents_via_api(params.dict()) 
        
        if not documents:
            logger.warning("No documents found via API for download request.")
            # Changed detail message slightly
            raise HTTPException(status_code=404, detail="未能获取到用于下载的文件列表。")

        logger.info(f"Preparing to download {len(documents)} files for zipping.")
        
        # 2. Prepare in-memory ZIP file
        zip_buffer = io.BytesIO()
        # Use compression for potentially smaller zip files
        # Allowing empty files just creates an empty zip, which might be acceptable
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zip_file:
            
            # 3. Download each file and add to ZIP asynchronously
            # Use a new client instance for downloads, potentially with different timeout/headers if needed
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as download_client: # Longer timeout, follow redirects
                 tasks = []
                 # Keep track of names used to avoid duplicates in the zip file
                 used_filenames_in_zip = set() 
                 
                 for i, doc in enumerate(documents):
                     url = doc.get('url')
                     original_name = doc.get('name', f'document_{i+1}') # Default name if missing
                     
                     # Sanitize filename for ZIP safety more thoroughly
                     safe_name_base = re.sub(r'[\\/*?\":<>|]', '_', original_name)
                     safe_name = safe_name_base + '.pdf' # Assume PDF initially

                     # Handle potential filename conflicts in the ZIP
                     counter = 1
                     while safe_name in used_filenames_in_zip:
                         safe_name = f"{safe_name_base}_{counter}.pdf"
                         counter += 1
                     used_filenames_in_zip.add(safe_name)
                          
                     if url:
                         # Pass the final safe name to the download function
                         tasks.append(download_and_zip(download_client, url, safe_name, zip_file))
                     else:
                          logger.warning(f"Skipping download for {safe_name} due to missing URL.")
                          
                 # Run downloads concurrently
                 logger.info(f"Gathering {len(tasks)} download tasks...")
                 results = await asyncio.gather(*tasks, return_exceptions=True)
                 
                 # Check for download errors
                 download_success_count = 0
                 download_errors = []
                 for i, result in enumerate(results):
                      # Find corresponding doc for logging, matching task order
                      doc_info = documents[i] if i < len(documents) else {} 
                      doc_name = doc_info.get('name', f'document_{i+1}')
                      
                      if isinstance(result, Exception):
                          # Store error details
                          download_errors.append({'name': doc_name, 'error': str(result)})
                          logger.error(f"Failed to download file '{doc_name}': {result}", exc_info=False) 
                      else:
                          # Assume success if no exception (download_and_zip doesn't return anything on success)
                          download_success_count += 1
                                   
        logger.info(f"Zip process completed. Success: {download_success_count}, Failed: {len(download_errors)}")
        
        # Add an info file to the zip if there were errors
        if download_errors:
            error_report = "文件下载报告:\n"
            error_report += f"成功: {download_success_count}\n"
            error_report += f"失败: {len(download_errors)}\n\n"
            error_report += "失败列表:\n"
            for err in download_errors:
                 error_report += f"- {err['name']}: {err['error']}\n"
            
            # Need to reopen the zip buffer in append mode to add the report
            with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED, allowZip64=True) as zip_file_append:
                 zip_file_append.writestr("_下载报告.txt", error_report.encode('utf-8'))


        # If ALL downloads failed, raise an error
        if download_success_count == 0 and len(documents) > 0:
              logger.error("All file downloads failed.")
              raise HTTPException(status_code=500, detail=f"所有 {len(documents)} 个文件都下载失败，无法创建有效的 ZIP 文件。")
        
        # 4. Prepare the response
        zip_buffer.seek(0) # Rewind buffer to the beginning
        
        # Create a safer default filename or derive from params
        default_zip_filename = f"法院文书_{params.sdbh}.zip"
        safe_zip_filename = re.sub(r'[\\/*?\":<>|]', '_', default_zip_filename) # Sanitize
        
        # URL-encode the filename for the Content-Disposition header
        encoded_zip_filename = quote(safe_zip_filename)
        
        logger.info(f"Returning ZIP file: {safe_zip_filename}")
        
        headers = {
            # Encode filename properly for broader compatibility using RFC 6266 syntax
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_zip_filename}" 
        }
        
        return StreamingResponse(zip_buffer, media_type='application/zip', headers=headers)

    except HTTPException as http_exc:
         # Log and re-raise HTTP exceptions from fetch_documents_via_api or self-raised
         logger.error(f"HTTPException during /download_all: {http_exc.status_code} - {http_exc.detail}")
         raise http_exc
    except Exception as e:
        logger.error(f"Unhandled error during /download_all process: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建 ZIP 文件时发生内部错误: {e}")

async def download_and_zip(client: httpx.AsyncClient, url: str, filename: str, zip_file: zipfile.ZipFile):
    """Helper coroutine to download a single file and add it to the zip."""
    # Use a reasonable timeout per file download
    timeout = httpx.Timeout(60.0, connect=10.0) 
    try:
        logger.info(f"Downloading: {url} as {filename}")
        async with client.stream("GET", url, timeout=timeout) as response:
            response.raise_for_status() # Check if download initiated successfully
            
            # Read content in chunks and write to zip directly to handle potentially large files
            # zipfile doesn't directly support async writing, so we read then write.
            # For very large files, saving to a temp file first might be better.
            content = await response.aread() # Read all content into memory for now

            # Add content to zip using writestr
            zip_file.writestr(filename, content)
            logger.info(f"Successfully added {filename} (Size: {len(content)} bytes) to ZIP.")
    except Exception as e:
        # Log the error and re-raise it to be caught by asyncio.gather
        logger.error(f"Error in download_and_zip for {filename} ({url}): {type(e).__name__} - {e}")
        raise e # Re-raise the original exception

# --- Run Server (for local development) ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Uvicorn server...")
    # Check if event loop is already running (e.g., in Jupyter)
    try:
        asyncio.get_running_loop()
        logger.info("Asyncio loop already running.")
    except RuntimeError:
        # No loop running, safe to start uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000) 
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
import requests
import time
import io
import re
import os
import urllib.parse
import json

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Amazon Scraper Hub", layout="wide")
st.title("🛒 Amazon Global Automated Scraper (Cloud Optimized)")

# --- CONSTANTS ---
PROGRESS_FILE = "amazon_scrape_progress.csv"

# --- AMAZON GLOBAL DOMAINS ---
AMAZON_DOMAINS = {
    "Egypt (.eg)": "www.amazon.eg",
    "United States (.com)": "www.amazon.com",
    "Canada (.ca)": "www.amazon.ca",
    "Mexico (.com.mx)": "www.amazon.com.mx",
    "United Kingdom (.co.uk)": "www.amazon.co.uk",
    "Germany (.de)": "www.amazon.de",
    "France (.fr)": "www.amazon.fr",
    "India (.in)": "www.amazon.in",
    "United Arab Emirates (.ae)": "www.amazon.ae",
    "Saudi Arabia (.sa)": "www.amazon.sa"
}

# --- SCRAPERAPI FETCH HELPER ---
def fetch_html_via_api(target_url):
    """
    Sends the Amazon URL to ScraperAPI to bypass blocks and return clean HTML.
    Uses premium/residential proxies automatically for Amazon.
    """
    try:
        api_key = st.secrets["SCRAPER_API_KEY"]
    except Exception:
        st.error("🔑 Missing SCRAPER_API_KEY in Streamlit Secrets! Please add it in your Streamlit Cloud dashboard.")
        return None

    payload = {
        'api_key': api_key,
        'url': target_url,
        'premium': 'true' 
    }
    
    proxy_url = "http://api.scraperapi.com/?" + urllib.parse.urlencode(payload)
    
    try:
        response = requests.get(proxy_url, timeout=60)
        if response.status_code == 200:
            return response.text
        else:
            st.error(f"API Error: Received status code {response.status_code}")
            return None
    except Exception as e:
        st.error(f"Request failed: {e}")
        return None

# --- LAYER 1: SELLER LINK EXTRACTION ---
def extract_seller_urls(seller_url, status_element):
    product_urls = []
    current_url = seller_url
    page_num = 1
    
    while current_url:
        status_element.text(f"🏬 Storefront: Extracting page {page_num}...")
        html = fetch_html_via_api(current_url)
        
        if not html:
            break
            
        soup = BeautifulSoup(html, 'html.parser')
        items = soup.select("div[data-asin]")
        page_items_count = 0 
        
        for item in items:
            asin = item.get('data-asin')
            if asin and len(asin) > 5:
                domain = re.search(r"https://(www\.amazon\.[a-z\.]+)/", current_url)
                base_domain = domain.group(1) if domain else "www.amazon.com"
                product_urls.append(f"https://{base_domain}/dp/{asin}")
                page_items_count += 1
                
        if page_items_count == 0:
            break
            
        next_button = soup.select_one("a.s-pagination-next")
        if next_button and "s-pagination-disabled" not in next_button.get("class", []):
            href = next_button.get("href")
            if href:
                if href.startswith("http"):
                    current_url = href
                else:
                    domain = re.search(r"https://(www\.amazon\.[a-z\.]+)", current_url)
                    base = domain.group(0) if domain else "https://www.amazon.com"
                    current_url = f"{base}{href}"
                page_num += 1
            else:
                current_url = None
        else:
            current_url = None
            
    return list(dict.fromkeys(product_urls))

# --- LAYER 2: PRODUCT DEEP DETAILS SCRAPER (UPGRADED) ---
def get_product_details(url):
    html = fetch_html_via_api(url)
    
    if not html:
        return {"URL": url, "Error": "Failed to retrieve page HTML via API"}
        
    soup = BeautifulSoup(html, 'html.parser')
    
    if "captcha" in html.lower() or "bot detection" in html.lower():
        return {"URL": url, "Title": "BLOCKED BY CAPTCHA", "Error": "Amazon Bot Detection"}

    # 1. CORE PRODUCT IDENTIFIERS
    title_el = soup.select_one("#productTitle")
    title = title_el.get_text().strip() if title_el else "None"
    
    brand_el = soup.select_one("#bylineInfo")
    brand = brand_el.get_text().strip() if brand_el else "None"
    
    # 2. PRICING & METRICS
    price_el = soup.select_one("#corePrice_feature_div .a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
    price = price_el.get_text().strip() if price_el else "None"

    rating_el = soup.select_one("#acrPopover")
    rating = rating_el.get("title").strip() if rating_el and rating_el.get("title") else "None"

    reviews_el = soup.select_one("#acrCustomerReviewText")
    reviews = reviews_el.get_text().strip() if reviews_el else "None"
    
    # 3. CATEGORY & TEXT DETAILS
    breadcrumb = []
    breadcrumb_ul = soup.select_one("#wayfinding-breadcrumbs_feature_div ul")
    if breadcrumb_ul:
        breadcrumb = [a.get_text().strip() for a in breadcrumb_ul.find_all('a')]

    about_items = []
    about_ul = soup.select_one("#feature-bullets ul")
    if about_ul:
        about_items = [li.get_text().strip() for li in about_ul.find_all('li') if not li.get('id')]

    desc_el = soup.select_one("#productDescription")
    product_description = desc_el.get_text().strip() if desc_el else "None"
        
    # 4. TECHNICAL SPECIFICATIONS
    details_dict = {}
    for li in soup.select("#detailBullets_feature_div li"):
        text = li.get_text().strip()
        text = re.sub(r'\s+', ' ', text) 
        if ":" in text:
            key, value = text.split(":", 1)
            details_dict[key.strip()] = value.strip()

    tech_specs_dict = {}
    for row in soup.select("#productDetails_techSpec_section_1 tr"):
        th = row.find("th")
        td = row.find("td")
        if th and td:
            tech_specs_dict[th.get_text().strip()] = td.get_text().strip()
            
    # 5. ADVANCED HIGH-RES IMAGE EXTRACTION
    image_urls = []
    
    scripts = soup.find_all('script')
    for script in scripts:
        if script.string and 'colorImages' in script.string:
            match = re.search(r'"colorImages":\s*\{"initial":\s*(\[.*?\])\}', script.string)
            if match:
                try:
                    images_data = json.loads(match.group(1))
                    for img in images_data:
                        if "hiRes" in img and img["hiRes"]:
                            image_urls.append(img["hiRes"])
                        elif "large" in img and img["large"]:
                            image_urls.append(img["large"])
                except Exception:
                    pass
            break 

    if not image_urls:
        for img in soup.select("#altImages img"):
            src = img.get("src")
            if src and ("." in src):
                clean_src = re.sub(r"\._.*_\.", ".", src) 
                if "media-amazon" in clean_src:
                    image_urls.append(clean_src)
    
    image_urls = list(dict.fromkeys(image_urls))
    images_dict = {f"Image {i+1}": img for i, img in enumerate(image_urls)}
    
    # 6. ASSEMBLE FINAL DATA RECORD
    result = {
        "URL": url, 
        "Title": title, 
        "Brand": brand, 
        "Price": price,
        "Rating": rating,
        "Reviews": reviews,
        "Breadcrumb": ", ".join(breadcrumb),
        "About This Item": "; ".join(about_items), 
        "Product Description": product_description,
    }
    result.update(images_dict)
    result.update(details_dict)
    result.update(tech_specs_dict)
    
    return result

# --- CONTROL USER INTERFACE ---
st.markdown("### 🛠️ Configuration Panel")
scrape_mode = st.selectbox(
    "Choose Scrape Operation Mode:",
    ["Option 1: Direct Product Scraping (Input URLs / Upload File)", 
     "Option 2: Full Seller Storefront Scraping (Auto-extract Links + Scrape Details)"]
)

input_format = "Full URLs"
selected_domain = "www.amazon.eg"

if "Option 1" in scrape_mode:
    input_format = st.radio("Input Type:", ["Full URLs", "ASINs"], horizontal=True)
    
    if input_format == "ASINs":
        region_name = st.selectbox("Select Amazon Region for ASINs:", list(AMAZON_DOMAINS.keys()), index=0)
        selected_domain = AMAZON_DOMAINS[region_name]

    col1, col2 = st.columns(2)
    with col1:
        urls_input = st.text_area(f"Paste {input_format} here (one per line):", height=150)
    with col2:
        uploaded_file = st.file_uploader(f"Or upload an Excel/CSV file containing {input_format}", type=['csv', 'xlsx'])
else:
    seller_input = st.text_input("Paste Amazon Seller Storefront URL (e.g., https://www.amazon.eg/s?me=...):")

st.markdown("### ⚙️ Run Settings")
resume_run = st.checkbox("🔄 Resume from stopped run (Skips already scraped URLs in saved file)", value=True)
clear_cache = st.button("🗑️ Clear Saved Progress File")

if clear_cache:
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        st.success("Previous progress deleted. Starting fresh next time.")
    else:
        st.info("No saved progress to delete.")

st.divider()

# --- EXECUTION ENGINE ---
if st.button("Run Extraction Pipeline", type="primary"):
    status_text = st.empty()
    final_urls = []
    should_continue = True
    
    # 1. Input Processing
    if "Option 1" in scrape_mode:
        raw_inputs = []
        if urls_input:
            raw_inputs.extend([val.strip() for val in urls_input.split('\n') if val.strip()])
            
        if uploaded_file is not None:
            try:
                df_input = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                col_names_to_check = ['url', 'urls', 'link', 'links', 'asin', 'asins']
                val_col = next((col for col in df_input.columns if str(col).strip().lower() in col_names_to_check), df_input.columns[0])
                raw_inputs.extend([str(val).strip() for val in df_input[val_col].dropna().tolist() if str(val).strip()])
            except Exception as e:
                st.error(f"Error parsing uploaded file: {e}")
                should_continue = False
        
        combined_urls = []
        if input_format == "ASINs":
            for val in raw_inputs:
                clean_asin = val.split('/')[-1] if 'amazon' in val.lower() else val
                combined_urls.append(f"https://{selected_domain}/dp/{clean_asin}")
        else:
            combined_urls = raw_inputs

        final_urls = list(dict.fromkeys(combined_urls))
        if not final_urls and should_continue:
            st.warning(f"Please enter {input_format} or upload a valid file.")
            should_continue = False
            
    else: 
        if not seller_input:
            st.warning("Please enter a valid seller URL.")
            should_continue = False

    # 2. Main Scrape Engine 
    if should_continue:
        if "Option 2" in scrape_mode:
            with st.spinner("Processing storefront mapping via API..."):
                final_urls = extract_seller_urls(seller_input, status_text)
                st.info(f"🏬 Storefront Map Complete: Discovered **{len(final_urls)}** target products.")

        if not final_urls:
            st.warning("No operational URLs located. Check inputs.")
        else:
            # --- RESUME LOGIC ---
            already_scraped = set()
            if resume_run and os.path.exists(PROGRESS_FILE):
                try:
                    existing_df = pd.read_csv(PROGRESS_FILE)
                    if "URL" in existing_df.columns:
                        already_scraped = set(existing_df["URL"].tolist())
                        st.info(f"🔄 Resuming... Found {len(already_scraped)} items already saved. Skipping those.")
                except Exception as e:
                    st.warning(f"Failed to read progress file. Starting fresh. Error: {e}")
            
            pending_urls = [u for u in final_urls if u not in already_scraped]

            if not pending_urls:
                st.success("✨ All URLs have already been scraped in a previous run!")
            else:
                progress_bar = st.progress(0)
                
                for index, url in enumerate(pending_urls):
                    status_text.text(f"📦 Progress: Processing pending item {index + 1} of {len(pending_urls)} → {url}")
                    
                    try:
                        scraped_data = get_product_details(url)
                        
                        # INCREMENTAL SAVE TO HARD DRIVE IMMEDIATELY (SAFE MERGE)
                        df_incremental = pd.DataFrame([scraped_data])
                        
                        if os.path.exists(PROGRESS_FILE):
                            try:
                                existing_df = pd.read_csv(PROGRESS_FILE)
                                # Safe merge: pd.concat aligns columns perfectly even if they differ
                                updated_df = pd.concat([existing_df, df_incremental], ignore_index=True)
                                updated_df.to_csv(PROGRESS_FILE, index=False)
                            except Exception:
                                df_incremental.to_csv(PROGRESS_FILE, index=False)
                        else:
                            df_incremental.to_csv(PROGRESS_FILE, index=False)
                            
                    except Exception as e:
                        st.error(f"Failed asset pull on {url}: {e}")
                    
                    progress_bar.progress((index + 1) / len(pending_urls))
                    
                status_text.success("✨ Processing pipeline finalized successfully!")
            
            # --- FINAL OUTPUT PRESENTATION ---
            if os.path.exists(PROGRESS_FILE):
                try:
                    final_df = pd.read_csv(PROGRESS_FILE)
                    st.dataframe(final_df)
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        final_df.to_excel(writer, index=False, sheet_name='Master Catalog Data')
                    
                    st.download_button(
                        label="📥 Download Consolidated Master Dataset (Excel)",
                        data=buffer.getvalue(),
                        file_name="amazon_master_catalog_details.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                except Exception as e:
                    st.error(f"Error reading the final output file: {e}")

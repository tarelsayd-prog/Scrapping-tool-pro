import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import io
import shutil
import re
import gc
import os

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Amazon Scraper Hub", layout="wide")
st.title("🛒 Amazon Global Automated Scraper")

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

# --- SELENIUM HEADLESS SETUP ---
def get_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')    
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    # Use a more randomized/updated user agent if bot detection persists
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
    
    chromium_path = shutil.which('chromium')
    chromedriver_path = shutil.which('chromedriver')
    
    if chromium_path and chromedriver_path:
        options.binary_location = chromium_path
        service = Service(chromedriver_path)
    else:
        service = Service(ChromeDriverManager().install())
        
    return webdriver.Chrome(service=service, options=options)

# --- LAYER 1: SELLER LINK EXTRACTION ---
def extract_seller_urls(driver, seller_url, status_element):
    product_urls = []
    current_url = seller_url
    page_num = 1
    
    while current_url:
        status_element.text(f"🏬 Storefront: Extracting page {page_num}...")
        driver.get(current_url)
        time.sleep(5)
        
        items = driver.find_elements(By.CSS_SELECTOR, "div[data-asin]")
        page_items_count = 0 
        
        for item in items:
            asin = item.get_attribute("data-asin")
            if asin and len(asin) > 5:
                domain = re.search(r"https://(www\.amazon\.[a-z\.]+)/", current_url)
                base_domain = domain.group(1) if domain else "www.amazon.com"
                product_urls.append(f"https://{base_domain}/dp/{asin}")
                page_items_count += 1
                
        if page_items_count == 0:
            break
            
        try:
            next_button = driver.find_elements(By.CSS_SELECTOR, "a.s-pagination-next")
            if next_button and "s-pagination-disabled" not in next_button[0].get_attribute("class"):
                current_url = next_button[0].get_attribute("href")
                page_num += 1
            else:
                current_url = None
        except Exception:
            current_url = None
            
    return list(dict.fromkeys(product_urls))

# --- LAYER 2: IMAGE EXTRACTION ---
def get_real_amazon_images(driver):
    image_urls = []
    try:
        thumbs = driver.find_elements(By.CSS_SELECTOR, "#altImages li img")
        for t in thumbs:
            try:
                t.click()
                time.sleep(0.3)
            except:
                pass

        scripts = driver.find_elements(By.TAG_NAME, "script")
        for script in scripts:
            content = script.get_attribute("innerHTML")
            if content and "colorImages" in content:
                hires = re.findall(r'"hiRes":"(https:[^"]+)"', content)
                large = re.findall(r'"large":"(https:[^"]+)"', content)
                main = re.findall(r'"mainUrl":"(https:[^"]+)"', content)
                if hires: image_urls.extend(hires)
                elif large: image_urls.extend(large)
                elif main: image_urls.extend(main)
                break

        if not image_urls:
            thumbnails = driver.find_elements(By.CSS_SELECTOR, "#altImages img")
            for img in thumbnails:
                src = img.get_attribute("src")
                if src:
                    image_urls.append(re.sub(r"\._.*_\.", ".", src))
    except Exception:
        pass 
    return list(set([img for img in image_urls if img and img != "null"]))[:7]

# --- LAYER 3: PRODUCT DEEP DETAILS SCRAPER ---
def get_product_details(driver, url):
    driver.get(url)
    time.sleep(5)  
    
    # Check for Captcha
    if "captcha" in driver.page_source.lower() or "bot" in driver.page_source.lower():
        return {"URL": url, "Title": "BLOCKED BY CAPTCHA", "Brand": "BLOCKED", "Error": "Amazon Bot Detection"}

    real_images = get_real_amazon_images(driver)
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    title_el = driver.find_elements(By.CSS_SELECTOR, "#productTitle")
    title = title_el[0].text.strip() if title_el else "None"
    
    brand_el = driver.find_elements(By.CSS_SELECTOR, "#bylineInfo")
    brand = brand_el[0].text.strip() if brand_el else "None"
    
    breadcrumb = []
    breadcrumb_el = driver.find_elements(By.CSS_SELECTOR, "#wayfinding-breadcrumbs_feature_div ul")
    if breadcrumb_el:
        breadcrumb = [a.text.strip() for a in breadcrumb_el[0].find_elements(By.TAG_NAME, 'a')]

    about_items = []
    about_el = driver.find_elements(By.CSS_SELECTOR, "#feature-bullets ul")
    if about_el:
        about_items = [li.text.strip() for li in about_el[0].find_elements(By.TAG_NAME, 'li')]

    desc_el = driver.find_elements(By.CSS_SELECTOR, "#productDescription")
    product_description = desc_el[0].text.strip() if desc_el else "None"
        
    details_dict = {}
    for row in driver.find_elements(By.CSS_SELECTOR, "#detailBullets_feature_div li"):
        text = row.text.strip()
        if ":" in text:
            key, value = text.split(":", 1)
            details_dict[key.strip()] = value.strip()

    tech_specs_dict = {}
    for row in driver.find_elements(By.CSS_SELECTOR, "#productDetails_techSpec_section_1 tr"):
        try:
            th = row.find_element(By.TAG_NAME, "th").text.strip()
            td = row.find_element(By.TAG_NAME, "td").text.strip()
            tech_specs_dict[th] = td
        except:
            pass
            
    images_dict = {f"Image {i+1}": img for i, img in enumerate(real_images)}
    
    result = {
        "URL": url, "Title": title, "Brand": brand, "Breadcrumb": ", ".join(breadcrumb),
        "About This Item": "; ".join(about_items), "Product Description": product_description,
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
            storefront_driver = get_driver()
            try:
                with st.spinner("Processing storefront mapping..."):
                    final_urls = extract_seller_urls(storefront_driver, seller_input, status_text)
                    st.info(f"🏬 Storefront Map Complete: Discovered **{len(final_urls)}** target products.")
            finally:
                storefront_driver.quit() 
                gc.collect()

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
                    
                    single_driver = get_driver()
                    try:
                        scraped_data = get_product_details(single_driver, url)
                        
                        # INCREMENTAL SAVE TO HARD DRIVE IMMEDIATELY
                        df_incremental = pd.DataFrame([scraped_data])
                        # Append to CSV. If file doesn't exist, write headers.
                        file_exists = os.path.exists(PROGRESS_FILE)
                        df_incremental.to_csv(PROGRESS_FILE, mode='a', header=not file_exists, index=False)
                        
                    except Exception as e:
                        st.error(f"Failed asset pull on {url}: {e}")
                    finally:
                        single_driver.quit()
                        gc.collect()
                    
                    progress_bar.progress((index + 1) / len(pending_urls))
                    
                status_text.success("✨ Processing pipeline finalized successfully!")
            
            # --- FINAL OUTPUT PRESENTATION ---
            if os.path.exists(PROGRESS_FILE):
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

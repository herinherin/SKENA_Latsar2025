import streamlit as st
import pandas as pd
import time
import io
import requests
import re
import os
import base64
from urllib.parse import quote
from bs4 import BeautifulSoup
from datetime import date

# --- Import Library Selenium ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# --- Konfigurasi Halaman Streamlit ---
st.set_page_config(
    page_title="SKENA",
    page_icon="🔍",
    layout="wide"
)

# --- Inisialisasi Session State ---
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "sub_page" not in st.session_state:
    st.session_state.sub_page = "Sosial"
if 'scraping_done' not in st.session_state:
    st.session_state.scraping_done = False
if 'excel_data' not in st.session_state:
    st.session_state.excel_data = None
if 'file_name' not in st.session_state:
    st.session_state.file_name = ""
if 'total_duration' not in st.session_state:
    st.session_state.total_duration = ""
if 'no_results' not in st.session_state:
    st.session_state.no_results = False

# --- Fungsi-Fungsi Inti ---

@st.cache_data
def load_data_from_url(url, sheet_name=0):
    """Memuat data dari URL Google Sheets ke dalam DataFrame."""
    try:
        df = pd.read_excel(url, sheet_name=sheet_name)
        return df
    except Exception as e:
        st.error(f"Gagal memuat data dari URL. Pastikan link dapat diakses. Error: {e}")
        return None

def get_rentang_tanggal(tahun: int, triwulan: str, start_date=None, end_date=None):
    """Menghasilkan tanggal awal dan akhir berdasarkan tahun dan triwulan atau tanggal custom."""
    if triwulan == "Tanggal Custom":
        if start_date and end_date:
            return start_date.strftime('%m/%d/%Y'), end_date.strftime('%m/%d/%Y')
        else:
            return None, None
            
    triwulan_dict = {
        "Triwulan 1": ("1/1", "3/31"),
        "Triwulan 2": ("4/1", "6/30"),
        "Triwulan 3": ("7/1", "9/30"),
        "Triwulan 4": ("10/1", "12/31")
    }
    awal, akhir = triwulan_dict[triwulan]
    return f"{awal}/{tahun}", f"{akhir}/{tahun}"

def ambil_ringkasan(link):
    """Mengambil ringkasan/deskripsi dari sebuah link berita."""
    try:
        response = requests.get(link, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')

        deskripsi = soup.find('meta', attrs={'name': 'description'})
        if deskripsi and deskripsi.get('content'): return deskripsi['content']

        og_desc = soup.find('meta', attrs={'property': 'og:description'})
        if og_desc and og_desc.get('content'): return og_desc['content']

        p_tag = soup.find('p')
        if p_tag: return p_tag.get_text(strip=True)
    except Exception:
        return ""
    return ""

def start_scraping(tanggal_awal, tanggal_akhir, kata_kunci_lapus_df, kata_kunci_daerah_df, start_time):
    """Fungsi utama yang membungkus seluruh logika scraping."""
    kata_kunci_lapus_dict = {c: kata_kunci_lapus_df[c].dropna().astype(str).str.strip().tolist() for c in kata_kunci_lapus_df.columns}
    kata_kunci_daerah_dict = {c: kata_kunci_daerah_df[c].dropna().astype(str).str.strip().tolist() for c in kata_kunci_daerah_df.columns}

    nama_daerah = "Konawe Selatan"
    if nama_daerah not in kata_kunci_daerah_dict:
        st.error(f"Kolom '{nama_daerah}' tidak ditemukan dalam data daerah.")
        return None

    kecamatan_list = kata_kunci_daerah_dict[nama_daerah]
    lokasi_filter = [nama_daerah.lower()] + [kec.lower() for kec in kecamatan_list]

    status_placeholder = st.empty()
    status_placeholder.info("Mempersiapkan browser...")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        st.error(f"Gagal memulai browser Chrome. Pastikan Chrome terinstal atau driver sudah benar. Error: {e}")
        return None

    semua_hasil_df = {}
    total_kategori = len(kata_kunci_lapus_dict)
    kategori_ke = 0
    for kategori, kata_kunci_list in kata_kunci_lapus_dict.items():
        kategori_ke += 1
        hasil_kategori, set_link = [], set()
        nomor = 1
        for keyword_raw in kata_kunci_list:
            elapsed_time = time.time() - start_time
            minutes = int(elapsed_time // 60)
            seconds = int(elapsed_time % 60)
            status_placeholder.info(f"⏳ Proses scraping sedang berjalan... ({minutes} menit {seconds} detik) | 📁 Memproses kategori {kategori_ke} dari {total_kategori}: {kategori}")

            if pd.isna(keyword_raw): continue
            keyword = str(keyword_raw).strip()
            if not keyword: continue
            
            st.text(f"  ➡️ 🔍 Mencari: {keyword}")
            
            query = quote(keyword + " " + nama_daerah)
            base_url = f"https://www.google.com/search?q={query}&tbm=nws&tbs=cdr:1,cd_min:{tanggal_awal},cd_max:{tanggal_akhir},sbd:1"

            try:
                driver.get(base_url)
                time.sleep(2)

                pagination_links = driver.find_elements(By.XPATH, '//a[contains(@href, "start=")]')
                start_values = {0}
                for link in pagination_links:
                    href = link.get_attribute("href")
                    match = re.search(r"[?&]start=(\d+)", href)
                    if match:
                        start_values.add(int(match.group(1)))
                
                for start in sorted(start_values):
                    page_url = base_url + f"&start={start}"
                    driver.get(page_url)
                    time.sleep(2)
                    
                    judul_elements = driver.find_elements(By.XPATH, "//div[@class='n0jPhd ynAwRc MBeuO nDgy9d']")
                    link_elements = driver.find_elements(By.XPATH, "//a[@class='WlydOe']")
                    tanggal_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'OSrXXb')]/span")

                    for judul_elem, link_elem, tanggal_elem in zip(judul_elements, link_elements, tanggal_elements):
                        try:
                            link = link_elem.get_attribute("href")
                            if link in set_link: continue

                            judul = judul_elem.text.strip()
                            tanggal = tanggal_elem.text.strip()
                            ringkasan = ambil_ringkasan(link)

                            if not any(loc in judul.lower() for loc in lokasi_filter) and not any(loc in ringkasan.lower() for loc in lokasi_filter):
                                continue
                            
                            if keyword.lower() not in ringkasan.lower():
                                continue

                            hasil_kategori.append({"Nomor": nomor, "Kata Kunci": keyword, "Judul": judul, "Link": link, "Tanggal": tanggal, "Ringkasan": ringkasan})
                            nomor += 1
                            set_link.add(link)
                        except Exception:
                            continue
            except TimeoutException:
                st.text(f"     -- Tidak ada hasil untuk '{keyword}'")
                continue
            except Exception as e:
                st.warning(f"Terjadi error saat memproses keyword '{keyword}'. Melanjutkan... Error: {type(e).__name__}")

        if hasil_kategori:
            df_kat = pd.DataFrame(hasil_kategori)
            semua_hasil_df[kategori] = df_kat
            st.markdown(f"**Hasil Pratinjau Kategori: {kategori}**")
            st.dataframe(df_kat.head(3), use_container_width=True)

    driver.quit()
    status_placeholder.empty()
    return semua_hasil_df

def display_pdf(file_path):
    """Fungsi untuk membaca file PDF dan menampilkannya di Streamlit."""
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
        pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf">'
        st.markdown(pdf_display, unsafe_allow_html=True)
        st.divider()
        st.download_button(
            label="Unduh PDF",
            data=pdf_bytes,
            file_name=os.path.basename(file_path),
            mime="application/pdf",
            use_container_width=True
        )
    else:
        st.error("File PDF tidak ditemukan. Pastikan file 'sample.pdf' ada di direktori yang sama.")

# --- Logika Sidebar ---
st.sidebar.title("Menu Navigasi SKENA")
st.sidebar.markdown("---")

if st.sidebar.button("🏠 Home", use_container_width=True, type="primary" if st.session_state.page == "Home" else "secondary"):
    st.session_state.page = "Home"
    st.rerun()

with st.sidebar.expander("⚙️ Scraping", expanded=st.session_state.page == "Scraping"):
    if st.button("Sosial", key="sb_sosial", use_container_width=True):
        st.session_state.page = "Scraping"
        st.session_state.sub_page = "Sosial"
        st.rerun()
    if st.button("Neraca", key="sb_neraca", use_container_width=True):
        st.session_state.page = "Scraping"
        st.session_state.sub_page = "Neraca"
        st.rerun()
    if st.button("Produksi", key="sb_produksi", use_container_width=True):
        st.session_state.page = "Scraping"
        st.session_state.sub_page = "Produksi"
        st.rerun()

if st.sidebar.button("📄 Perlu dibaca", use_container_width=True, type="primary" if st.session_state.page == "Perlu dibaca" else "secondary"):
    st.session_state.page = "Perlu dibaca"
    st.rerun()
if st.sidebar.button("🗂️ Dokumentasi", use_container_width=True, type="primary" if st.session_state.page == "Dokumentasi" else "secondary"):
    st.session_state.page = "Dokumentasi"
    st.rerun()

# --- Konten Halaman Utama ---

if st.session_state.page == "Home":
    st.title("SKENA")
    st.header("Sistem Scraping Fenomena Konawe Selatan")
    st.markdown("Halo! Sistem ini merupakan alat bantu BPS Kab. Konawe Selatan untuk pengumpulan data. Apa yang ingin Anda scraping hari ini?")
    st.markdown("---")
    col1, col2, col3 = st.columns(3, gap="large")
    with col1:
        with st.container(border=True):
            st.subheader("👥 Sosial")
            st.write("Data terkait demografi, kemiskinan, pendidikan, dan kesehatan.")
            if st.button("Pilih Sosial", key="home_sosial", use_container_width=True):
                st.session_state.page = "Scraping"
                st.session_state.sub_page = "Sosial"
                st.rerun()
    with col2:
        with st.container(border=True):
            st.subheader("📈 Neraca")
            st.write("Data mengenai neraca perdagangan, PDB, inflasi, dan ekonomi lainnya.")
            if st.button("Pilih Neraca", key="home_neraca", use_container_width=True):
                st.session_state.page = "Scraping"
                st.session_state.sub_page = "Neraca"
                st.rerun()
    with col3:
        with st.container(border=True):
            st.subheader("🌾 Produksi")
            st.write("Informasi seputar produksi tanaman pangan, perkebunan, dan pertanian.")
            if st.button("Pilih Produksi", key="home_produksi", use_container_width=True):
                st.session_state.page = "Scraping"
                st.session_state.sub_page = "Produksi"
                st.rerun()

elif st.session_state.page == "Scraping":
    st.title(f"⚙️ Halaman Scraping Data - {st.session_state.sub_page}")
    st.markdown("---")

    if st.session_state.sub_page == "Sosial":
        st.info("Ini adalah area untuk fitur scraping data Sosial.")

    elif st.session_state.sub_page == "Neraca":
        url_lapus = "https://docs.google.com/spreadsheets/d/19FRmYvDvjhCGL3vDuOLJF54u7U7hnfic/export?format=xlsx"
        url_daerah = "https://docs.google.com/spreadsheets/d/1Y2SbHlWBWwcxCdAhHiIkdQmcmq--NkGk/export?format=xlsx"

        if st.session_state.scraping_done:
            st.header("✅ Proses Selesai")
            st.success(f"Scraping telah selesai dalam {st.session_state.total_duration}. Anda dapat mengunduh hasilnya di bawah.")
            st.download_button(label="📥 Unduh Hasil Scraping (Excel)", data=st.session_state.excel_data, file_name=st.session_state.file_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            if st.button("🔄 Mulai Scraping Baru (Reset)", use_container_width=True):
                st.session_state.scraping_done = False
                st.session_state.excel_data = None
                st.session_state.file_name = ""
                st.session_state.total_duration = ""
                st.session_state.no_results = False
                st.rerun()
        elif st.session_state.no_results:
            st.header("⚠️ Tidak Ada Hasil")
            st.warning("Tidak ada berita yang ditemukan sesuai dengan parameter dan kata kunci yang Anda pilih.")
            if st.button("🔄 Coba Lagi", use_container_width=True):
                st.session_state.no_results = False
                st.rerun()
        else:
            if st.button("🔄 Muat Ulang Data Kata Kunci"):
                st.cache_data.clear()
                st.success("Cache data telah dibersihkan. Memuat data baru...")
            with st.spinner("Memuat data kata kunci dari Google Sheets..."):
                df_lapus = load_data_from_url(url_lapus, sheet_name='Sheet1')
                df_daerah = load_data_from_url(url_daerah)

            if df_lapus is not None and df_daerah is not None:
                st.success("✅ Data kata kunci berhasil dimuat.")
                original_categories = df_lapus.columns.tolist()
                grouped_categories = sorted(list(set([re.match(r'([A-Z]+)', cat).group(1) for cat in original_categories])))
                
                st.header("Atur Parameter Scraping")
                with st.form("scraping_form"):
                    
                    # --- Input Tanggal dan Tahun ---
                    tahun_list = ["--Pilih Tahun--"] + list(range(2020, 2026))
                    tahun_input = st.selectbox("Pilih Tahun:", options=tahun_list)

                    triwulan_list = ["--Pilih Triwulan--", "Triwulan 1", "Triwulan 2", "Triwulan 3", "Triwulan 4", "Tanggal Custom"]
                    triwulan_input = st.selectbox("Pilih Triwulan:", options=triwulan_list)

                    start_date, end_date = None, None
                    if triwulan_input == "Tanggal Custom":
                        col1, col2 = st.columns(2)
                        with col1:
                            start_date = st.date_input("Masukkan tanggal awal", date.today())
                        with col2:
                            end_date = st.date_input("Masukkan tanggal akhir", date.today())
                    
                    st.markdown("---")
                    
                    # --- Input Kategori ---
                    opsi_kategori_list = ["--Pilih Opsi Kategori--", "Proses Semua Kategori", "Pilih Kategori Tertentu"]
                    mode_kategori = st.selectbox("Pilih Opsi Kategori:", opsi_kategori_list)
                    
                    kategori_terpilih_grouped = []
                    if mode_kategori == 'Pilih Kategori Tertentu':
                        kategori_terpilih_grouped = st.multiselect(
                            'Pilih satu atau lebih grup kategori untuk diproses:',
                            options=grouped_categories
                        )
                    
                    # --- Validasi & Tombol Submit ---
                    is_disabled = (
                        tahun_input == "--Pilih Tahun--" or
                        triwulan_input == "--Pilih Triwulan--" or
                        mode_kategori == "--Pilih Opsi Kategori--" or
                        (mode_kategori == 'Pilih Kategori Tertentu' and not kategori_terpilih_grouped)
                    )
                    
                    submitted = st.form_submit_button("🚀 Mulai Scraping", use_container_width=True, type="primary", disabled=is_disabled)

                if submitted:
                    tanggal_awal, tanggal_akhir = get_rentang_tanggal(int(tahun_input), triwulan_input, start_date, end_date)
                    
                    start_time = time.time()
                    timestamp = time.strftime("%Y%m%d-%H%M%S")
                    df_lapus_untuk_proses = df_lapus

                    if mode_kategori == 'Pilih Kategori Tertentu':
                        kategori_asli_untuk_diproses = []
                        for group in kategori_terpilih_grouped:
                            for original in original_categories:
                                if original.startswith(group):
                                    kategori_asli_untuk_diproses.append(original)
                        df_lapus_untuk_proses = df_lapus[kategori_asli_untuk_diproses]
                    
                    st.header("Proses & Hasil Scraping")
                    if mode_kategori == 'Pilih Kategori Tertentu':
                        nama_kategori_str = ', '.join(kategori_terpilih_grouped)
                        st.info(f"Memulai Scraping Kategori Grup: {nama_kategori_str} (Periode: {tanggal_awal} - {tanggal_akhir})")
                    else:
                        st.info(f"Memulai Scraping Seluruh Kategori (Periode: {tanggal_awal} - {tanggal_akhir})")

                    hasil_dict = start_scraping(tanggal_awal, tanggal_akhir, df_lapus_untuk_proses, df_daerah, start_time)
                    
                    end_time = time.time()
                    total_duration = end_time - start_time
                    total_minutes = int(total_duration // 60)
                    total_seconds = int(total_duration % 60)
                    st.session_state.total_duration = f"{total_minutes} menit {total_seconds} detik"

                    if hasil_dict:
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            for kategori, df in hasil_dict.items():
                                nama_sheet = f"Kategori {kategori}"
                                df.to_excel(writer, sheet_name=nama_sheet[:31], index=False)
                        
                        st.session_state.excel_data = output.getvalue()
                        st.session_state.file_name = f"Hasil_Scraping_{timestamp}.xlsx"
                        st.session_state.scraping_done = True
                        st.rerun()
                    else:
                        st.session_state.no_results = True
                        st.rerun()
            else:
                st.error("Gagal memuat data kata kunci. Aplikasi tidak dapat berjalan.")

    elif st.session_state.sub_page == "Produksi":
        st.info("Ini adalah area untuk fitur scraping data Produksi.")

elif st.session_state.page == "Perlu dibaca":
    st.title("📄 Perlu dibaca")
    st.markdown("Dokumen di bawah ini berisi panduan penting mengenai penggunaan aplikasi dan metodologi scraping data.")
    st.markdown("---")
    pdf_file_path = "sample.pdf"
    display_pdf(pdf_file_path)

elif st.session_state.page == "Dokumentasi":
    st.title("🗂️ Dokumentasi")
    st.markdown("Seluruh file, dataset, dan dokumentasi terkait proyek ini tersimpan di Google Drive berikut.")
    st.markdown("---")
    folder_id = "1z1_w_FyFmNB7ExfVzFVc3jH5InWmQSvZ"
    if folder_id == "YOUR_FOLDER_ID":
        st.warning("Harap ganti `YOUR_FOLDER_ID` di dalam kode dengan ID folder Google Drive Anda.")
    else:
        embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}"
        st.components.v1.html(f'<iframe src="{embed_url}" width="100%" height="600" style="border:1px solid #ddd; border-radius: 8px;"></iframe>', height=620)

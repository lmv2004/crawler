from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

def fetch_gold_data(url):
    """
    Hàm fetch dữ liệu từ URL
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Kiểm tra nếu là XML
        if 'xml' in url.lower() or 'xml' in response.headers.get('Content-Type', ''):
            return parse_xml_data(response.content)
        else:
            return parse_html_data(response.content, url)
            
    except Exception as e:
        raise Exception(f"Lỗi khi fetch dữ liệu: {str(e)}")

def parse_xml_data(content):
    """
    Parse dữ liệu XML (ví dụ: SJC)
    """
    soup = BeautifulSoup(content, 'xml')
    data = []
    
    # Thử parse các format XML khác nhau
    items = soup.find_all('item')
    if items:
        for item in items:
            row = {}
            for attr in item.attrs:
                row[attr.replace('@', '')] = item.get(attr)
            if row:
                data.append(row)
    else:
        # Parse các thẻ XML thông thường
        for item in soup.find_all():
            if item.name and not item.find_all():
                text = item.get_text(strip=True)
                if text:
                    data.append({'tag': item.name, 'value': text})
    
    return data

def parse_html_data(content, url):
    """
    Parse dữ liệu HTML từ các bảng
    """
    soup = BeautifulSoup(content, 'html.parser')
    data = []
    
    # Tìm tất cả các bảng trong trang
    tables = soup.find_all('table')
    
    if not tables:
        # Nếu không có bảng, thử tìm các div có class chứa "gold", "price", "gia"
        potential_elements = soup.find_all(['div', 'section'], 
                                          class_=re.compile(r'(gold|price|gia|vang)', re.I))
        
        for element in potential_elements[:5]:  # Giới hạn 5 phần tử đầu
            text = element.get_text(strip=True)
            if len(text) > 10 and len(text) < 200:
                data.append({
                    'noi_dung': text[:100],
                    'nguon': 'div/section'
                })
        
        if not data:
            raise Exception("Không tìm thấy bảng hoặc dữ liệu giá vàng trên trang")
        
        return data
    
    # Parse bảng đầu tiên có dữ liệu
    for table in tables:
        rows = table.find_all('tr')
        
        if len(rows) < 2:
            continue
            
        # Lấy headers
        headers = []
        header_row = rows[0]
        for th in header_row.find_all(['th', 'td']):
            header_text = th.get_text(strip=True)
            headers.append(header_text if header_text else f'Cột_{len(headers)+1}')
        
        if not headers:
            continue
        
        # Lấy dữ liệu
        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            if len(cols) > 0:
                row_data = {}
                for i, col in enumerate(cols):
                    header = headers[i] if i < len(headers) else f'Cột_{i+1}'
                    row_data[header] = col.get_text(strip=True)
                data.append(row_data)
        
        if data:
            break
    
    # Thêm timestamp
    for item in data:
        item['thoi_gian'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return data

def fetch_multiple_urls(urls, max_workers=5):
    """
    Fetch dữ liệu từ nhiều URL cùng lúc sử dụng ThreadPoolExecutor
    """
    all_data = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_gold_data, url): url for url in set(urls)}
        
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                data = future.result()
                if data:
                    all_data.extend(data)
            except Exception as e:
                errors.append(f"Lỗi khi tải {url}: {str(e)}")
                
    if not all_data and errors:
        raise Exception(" | ".join(errors))
        
    return all_data

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/preview', methods=['POST'])
def preview():
    """
    API xem trước dữ liệu
    """
    try:
        data = request.get_json()
        url_input = data.get('url', '')
        
        # Hỗ trợ URL là chuỗi (có thể chứa nhiều URL cách nhau bởi dấu phẩy) hoặc là list
        if isinstance(url_input, str):
            urls = [u.strip() for u in url_input.split(',') if u.strip()]
        elif isinstance(url_input, list):
            urls = [u.strip() for u in url_input if isinstance(u, str) and u.strip()]
        else:
            urls = []
            
        if not urls:
            return jsonify({'success': False, 'error': 'URL không được để trống'}), 400
        
        gold_data = fetch_multiple_urls(urls)
        
        return jsonify({
            'success': True,
            'data': gold_data[:50],  # Giới hạn 50 dòng để preview
            'total': len(gold_data)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def download():
    """
    API tải xuống file CSV
    """
    try:
        data = request.get_json()
        url_input = data.get('url', '')
        
        if isinstance(url_input, str):
            urls = [u.strip() for u in url_input.split(',') if u.strip()]
        elif isinstance(url_input, list):
            urls = [u.strip() for u in url_input if isinstance(u, str) and u.strip()]
        else:
            urls = []
            
        if not urls:
            return jsonify({'success': False, 'error': 'URL không được để trống'}), 400
        
        gold_data = fetch_multiple_urls(urls)
        
        if not gold_data:
            return jsonify({'success': False, 'error': 'Không có dữ liệu để tải xuống'}), 404
        
        # Tạo DataFrame và chuyển thành CSV
        df = pd.DataFrame(gold_data)
        
        # Tạo file CSV trong memory
        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'giavang_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
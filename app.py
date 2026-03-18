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
    
    # Parse tất cả các bảng
    for table in tables:
        rows = table.find_all('tr')
        
        if len(rows) < 2:
            continue
            
        # Lấy headers
        headers = []
        header_row = rows[0]
        
        # Xử lý headers
        for th in header_row.find_all(['th', 'td']):
            header_text = th.get_text(strip=True)
            cs = int(th.get('colspan', 1))
            for _ in range(cs):
                headers.append(header_text if header_text else f'Cột_{len(headers)+1}')
        
        if not headers:
            continue
            
        rowspan_data = {}
        # Lấy dữ liệu
        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            if len(cols) == 0 and len(rowspan_data) == 0:
                continue
                
            row_data = {}
            col_idx = 0
            col_element_idx = 0
            
            while col_element_idx < len(cols) or col_idx in rowspan_data:
                if col_idx in rowspan_data and rowspan_data[col_idx]['span'] > 0:
                    header = headers[col_idx] if col_idx < len(headers) else f'Cột_{col_idx+1}'
                    row_data[header] = rowspan_data[col_idx]['text']
                    rowspan_data[col_idx]['span'] -= 1
                    col_idx += 1
                elif col_element_idx < len(cols):
                    col = cols[col_element_idx]
                    text = col.get_text(strip=True)
                    rs = int(col.get('rowspan', 1))
                    cs = int(col.get('colspan', 1))
                    
                    header = headers[col_idx] if col_idx < len(headers) else f'Cột_{col_idx+1}'
                    row_data[header] = text
                    
                    if rs > 1:
                        for i in range(cs):
                            rowspan_data[col_idx + i] = {'span': rs - 1, 'text': text}
                            
                    col_idx += cs
                    col_element_idx += 1
                else:
                    break
            
            if row_data:
                date_match = re.search(r'(\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{4}/\d{2}/\d{2})', url)
                if date_match:
                    row_data['Ngày Dữ Liệu'] = date_match.group(1)
                row_data['URL_Nguồn'] = url
                data.append(row_data)
    
    # Thêm timestamp cào dữ liệu
    for item in data:
        item['Thời Gian Cào DL'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return data

def fetch_multiple_urls(urls, max_workers=20):
    """
    Fetch dữ liệu từ nhiều URL cùng lúc sử dụng ThreadPoolExecutor.
    Bỏ qua các URL không có dữ liệu (ngày nghỉ, thiếu data) thay vì báo lỗi.
    """
    all_data = []
    errors = []
    success_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_gold_data, url): url for url in set(urls)}

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                data = future.result()
                if data:
                    all_data.extend(data)
                    success_count += 1
                else:
                    errors.append(f"{url}: không có dữ liệu")
            except Exception as e:
                # Chỉ ghi nhận lỗi này, không làm tô toàn bộ batch thất bại
                errors.append(f"{url}: {str(e)}")

    return {
        'data': all_data,
        'success_count': success_count,
        'error_count': len(errors),
        'errors': errors   # danh sách URL lỗi / không có dữ liệu
    }

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
        
        result = fetch_multiple_urls(urls)
        gold_data = result['data']
        
        if not gold_data:
            err_sample = "; ".join(result['errors'][:3])
            return jsonify({
                'success': False,
                'error': f"Không tìm thấy dữ liệu trên tất cả {len(urls)} URL. Có thể trang web không có dữ liệu cho ngày này hoặc cấu trúc trang đã thay đổi. Chi tiết: {err_sample}"
            }), 404

        summary = f"✓ Tìm thấy {len(gold_data)} dòng từ {result['success_count']}/{len(urls)} URL"
        if result['error_count'] > 0:
            summary += f" ({result['error_count']} ngày không có dữ liệu, bỏ qua)"

        return jsonify({
            'success': True,
            'data': gold_data[:50],
            'total': len(gold_data),
            'summary': summary
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
        
        result = fetch_multiple_urls(urls)
        gold_data = result['data']

        if not gold_data:
            err_sample = "; ".join(result['errors'][:3])
            return jsonify({
                'success': False,
                'error': f"Không tìm thấy dữ liệu trên tất cả {len(urls)} URL. Có thể trang không có dữ liệu cho khoảng ngày này. Chi tiết: {err_sample}"
            }), 404
        
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
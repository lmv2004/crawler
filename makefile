# Makefile cho Crawler Giá Vàng

# Cài đặt các thư viện cần thiết
install:
	pip install flask
	pip install beautifulsoup4
	pip install requests
	pip install pandas
	pip install lxml

# Chạy ứng dụng
run:
	python app.py

# Chạy ứng dụng ở chế độ production
prod:
	python app.py

# Cài đặt và chạy
setup:
	make install
	make run

# Xóa file cache Python
clean:
	del /f /s /q *.pyc 2>nul
	del /f /s /q __pycache__ 2>nul
	rmdir /s /q __pycache__ 2>nul

# Hiển thị trợ giúp
help:
	@echo "Cac lenh co san:"
	@echo "  make install  - Cai dat cac thu vien"
	@echo "  make run      - Chay ung dung"
	@echo "  make setup    - Cai dat va chay ung dung"
	@echo "  make clean    - Xoa file cache"
	@echo "  make help     - Hien thi huong dan"

.PHONY: install run prod setup clean help
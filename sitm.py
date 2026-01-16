#!/usr/bin/env python3
"""
brarchive 파일을 디코딩하는 Streamlit 웹 애플리케이션
"""
import streamlit as st
import struct
import os
import zipfile
import tempfile
from pathlib import Path
import io

# brarchive 상수
MAGIC = 0x267052A0B125277D
ENTRY_NAME_LEN_MAX = 247
VERSIONS = [1]

# 페이지 설정
st.set_page_config(
    page_title="BRArchive 디코더",
    page_icon="📦",
    layout="wide"
)

def read_header(data, offset=0):
    """헤더 읽기"""
    magic = struct.unpack('<Q', data[offset:offset+8])[0]
    if magic != MAGIC:
        raise ValueError(f"Magic mismatch: expected {hex(MAGIC)}, got {hex(magic)}")
    
    entries = struct.unpack('<I', data[offset+8:offset+12])[0]
    version = struct.unpack('<I', data[offset+12:offset+16])[0]
    
    if version not in VERSIONS:
        raise ValueError(f"Unsupported version: {version}")
    
    return entries, version, offset + 16

def read_entry_descriptor(data, offset):
    """엔트리 디스크립터 읽기"""
    name_len = struct.unpack('<B', data[offset:offset+1])[0]
    
    if name_len > ENTRY_NAME_LEN_MAX:
        raise ValueError(f"Entry name too long: {name_len}")
    
    name = data[offset+1:offset+1+name_len].decode('utf-8')
    contents_offset = struct.unpack('<I', data[offset+1+ENTRY_NAME_LEN_MAX:offset+1+ENTRY_NAME_LEN_MAX+4])[0]
    contents_len = struct.unpack('<I', data[offset+1+ENTRY_NAME_LEN_MAX+4:offset+1+ENTRY_NAME_LEN_MAX+8])[0]
    
    next_offset = offset + 1 + ENTRY_NAME_LEN_MAX + 8
    
    return name, contents_offset, contents_len, next_offset

def decode_brarchive_to_dict(data):
    """brarchive 파일을 딕셔너리로 디코딩 (Rust 라이브러리와 동일한 로직)"""
    # 헤더 읽기
    entries_count, version, header_end = read_header(data)
    
    # 엔트리 디스크립터들 읽기
    entry_descriptors = []
    offset = header_end
    
    for i in range(entries_count):
        name, contents_offset, contents_len, next_offset = read_entry_descriptor(data, offset)
        entry_descriptors.append((name, contents_offset, contents_len))
        offset = next_offset
    
    # 콘텐츠 영역 시작 위치 (디스크립터들 뒤)
    contents_start = offset
    
    # 각 파일 추출
    files_dict = {}
    for name, contents_offset, contents_len in entry_descriptors:
        # 파일 내용 읽기
        actual_offset = contents_start + contents_offset
        file_contents = data[actual_offset:actual_offset + contents_len]
        files_dict[name] = file_contents
    
    return files_dict, entries_count, version

def create_zip_from_files(files_dict):
    """파일 딕셔너리로부터 ZIP 파일 생성"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for name, contents in files_dict.items():
            zip_file.writestr(name, contents)
    zip_buffer.seek(0)
    return zip_buffer

def encode_brarchive(files_dict):
    """파일 딕셔너리를 brarchive 형식으로 인코딩"""
    # 헤더 작성
    buf = bytearray()
    
    # Magic (8 bytes)
    buf.extend(struct.pack('<Q', MAGIC))
    
    # Entries count (4 bytes)
    entries_count = len(files_dict)
    buf.extend(struct.pack('<I', entries_count))
    
    # Version (4 bytes)
    buf.extend(struct.pack('<I', 1))
    
    # 엔트리 디스크립터들 작성
    descriptors = []
    current_offset = 0
    
    for name, content in sorted(files_dict.items()):  # 정렬하여 일관성 유지
        name_bytes = name.encode('utf-8')
        name_len = len(name_bytes)
        
        if name_len > ENTRY_NAME_LEN_MAX:
            raise ValueError(f"Entry name too long: {name_len}")
        
        content_len = len(content)
        
        descriptors.append({
            'name': name_bytes,
            'name_len': name_len,
            'offset': current_offset,
            'length': content_len
        })
        
        current_offset += content_len
    
    # 디스크립터들 쓰기
    for desc in descriptors:
        # Name length (1 byte)
        buf.append(desc['name_len'])
        # Name (247 bytes, 패딩 포함)
        name_buf = bytearray(ENTRY_NAME_LEN_MAX)
        name_buf[:desc['name_len']] = desc['name']
        buf.extend(name_buf)
        # Contents offset (4 bytes)
        buf.extend(struct.pack('<I', desc['offset']))
        # Contents length (4 bytes)
        buf.extend(struct.pack('<I', desc['length']))
    
    # 콘텐츠 영역 쓰기
    for name, content in sorted(files_dict.items()):
        buf.extend(content)
    
    return bytes(buf)

# 메인 UI
st.title("📦 BRArchive 디코더/인코더")
st.markdown("---")

# 탭 생성
tab1, tab2 = st.tabs(["디코딩", "인코딩"])

with tab1:
    # 파일 업로드
    uploaded_file = st.file_uploader(
        "brarchive 파일을 업로드하세요",
        type=None,  # 모든 파일 타입 허용 (확장자 체크는 아래에서 수행)
        help=".brarchive 또는 .BRArchive 확장자를 가진 파일을 업로드하세요",
        key="decode_uploader"
    )

    # 파일 확장자 체크 (대소문자 무시)
    if uploaded_file is not None:
        file_ext = Path(uploaded_file.name).suffix.lower()
        if file_ext != '.brarchive':
            st.error(f"❌ 지원하지 않는 파일 형식입니다. .brarchive 또는 .BRArchive 파일만 업로드할 수 있습니다. (업로드된 파일: {uploaded_file.name})")
            st.stop()

    if uploaded_file is not None:
        try:
            # 파일 읽기
            data = uploaded_file.read()
            
            # 디코딩
            with st.spinner("파일을 디코딩하는 중..."):
                files_dict, entries_count, version = decode_brarchive_to_dict(data)
            
            if entries_count == 0:
                st.warning("이 아카이브는 빈 아카이브입니다. (파일이 0개)")
            else:
                st.success(f"디코딩 완료! (파일 수: {entries_count}, 버전: {version})")
            
            # 사이드바에 파일 목록 표시
            if len(files_dict) > 0:
                with st.sidebar:
                    st.header("파일 목록")
                    selected_file = st.selectbox(
                        "파일 선택",
                        options=list(files_dict.keys()),
                        key="file_selector"
                    )
            else:
                st.info("이 아카이브에는 파일이 없습니다.")
                selected_file = None
            
            # 메인 영역
            if selected_file is not None:
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.subheader(f"{selected_file}")
                    
                    # 파일 내용 표시 (expander로 접기/펼치기 가능)
                    file_content = files_dict[selected_file]
                    
                    # 이미지 파일인지 확인
                    is_image = False
                    image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tga']
                    file_ext_lower = Path(selected_file).suffix.lower()
                    
                    if file_ext_lower in image_extensions:
                        is_image = True
                    
                    # 파일 미리보기를 expander로 감싸기
                    with st.expander(f"파일 미리보기", expanded=False):
                        if is_image:
                            try:
                                from PIL import Image
                                import io as image_io
                                img = Image.open(image_io.BytesIO(file_content))
                                st.image(img, caption=selected_file, use_container_width=True)
                                st.info(f"이미지 크기: {img.size[0]} x {img.size[1]} pixels")
                            except Exception as e:
                                st.warning(f"이미지 로드 실패: {str(e)}")
                                is_image = False
                        
                        if not is_image:
                            # JSON 파일인지 확인
                            try:
                                import json
                                if selected_file.endswith('.json'):
                                    json_content = json.loads(file_content.decode('utf-8'))
                                    st.json(json_content)
                                else:
                                    # 텍스트 파일인지 확인
                                    try:
                                        text_content = file_content.decode('utf-8')
                                        st.code(text_content, language='text')
                                    except UnicodeDecodeError:
                                        # 바이너리 파일
                                        st.info("이 파일은 바이너리 파일입니다.")
                            except json.JSONDecodeError:
                                # JSON 파싱 실패
                                try:
                                    text_content = file_content.decode('utf-8')
                                    st.code(text_content, language='text')
                                except UnicodeDecodeError:
                                    st.info("이 파일은 바이너리 파일입니다.")
                    
                    # 다운로드 버튼은 항상 표시
                    st.download_button(
                        label="파일 다운로드",
                        data=file_content,
                        file_name=selected_file,
                        mime="application/octet-stream",
                        key=f"download_{selected_file}"
                    )
                
                with col2:
                    st.subheader("정보")
                    st.metric("총 파일 수", entries_count)
                    st.metric("아카이브 버전", version)
                    if selected_file is not None:
                        st.metric("선택된 파일 크기", f"{len(files_dict[selected_file]):,} bytes")
            
            # 전체 다운로드 및 파일 목록
            st.markdown("---")
            col_download, col_list = st.columns([1, 2])
            
            with col_download:
                st.subheader("다운로드")
                if len(files_dict) > 0:
                    zip_buffer = create_zip_from_files(files_dict)
                    # 파일명에서 확장자 제거 (대소문자 무시)
                    base_name = Path(uploaded_file.name).stem
                    st.download_button(
                        label="전체 파일 ZIP 다운로드",
                        data=zip_buffer,
                        file_name=f"{base_name}_decoded.zip",
                        mime="application/zip"
                    )
                else:
                    st.info("다운로드할 파일이 없습니다.")
            
            # 파일 목록 테이블
            if len(files_dict) > 0:
                st.markdown("---")
                st.subheader("모든 파일 목록")
                
                file_list_data = []
                image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tga']
                for name, content in files_dict.items():
                    file_ext = Path(name).suffix.lower()
                    if file_ext in image_extensions:
                        file_type = "이미지"
                    elif name.endswith('.json'):
                        file_type = "JSON"
                    else:
                        try:
                            # 텍스트 파일인지 확인
                            content[:100].decode('utf-8')
                            file_type = "텍스트"
                        except:
                            file_type = "바이너리"
                    
                    file_list_data.append({
                        "파일명": name,
                        "크기 (bytes)": len(content),
                        "타입": file_type
                    })
                
                st.dataframe(file_list_data, use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ 오류 발생: {str(e)}")
            st.exception(e)
    else:
        st.info("👆 위에서 brarchive 파일을 업로드하세요")
        
        # 예시 정보
        with st.expander("BRArchive란?"):
            st.markdown("""
            BRArchive는 Minecraft Bedrock Edition에서 사용하는 아카이브 포맷입니다.
            여러 파일을 하나의 .brarchive 파일로 묶어서 저장합니다.
            
            **지원 기능:**
            - brarchive 파일 업로드 및 디코딩
            - 파일 내용 미리보기 (JSON, 텍스트, 이미지)
            - 개별 파일 다운로드
            - 전체 파일 ZIP 다운로드
            """)

with tab2:
    st.header("BRArchive 인코딩")
    st.markdown("---")
    
    st.subheader("파일 업로드")
    uploaded_files = st.file_uploader(
        "인코딩할 파일들을 업로드하세요 (여러 파일 선택 가능)",
        type=None,
        accept_multiple_files=True,
        help="이미지, 텍스트, JSON 등 모든 파일 타입을 지원합니다",
        key="encode_uploader"
    )
    
    if uploaded_files:
        st.info(f"{len(uploaded_files)}개의 파일이 업로드되었습니다.")
        
        # 파일 딕셔너리 생성
        files_dict = {}
        for uploaded_file in uploaded_files:
            files_dict[uploaded_file.name] = uploaded_file.read()
        
        # 파일 목록 표시
        st.subheader("업로드된 파일 목록")
        file_list = []
        for name, content in files_dict.items():
            file_ext = Path(name).suffix.lower()
            file_type = "이미지" if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tga'] else \
                        "JSON" if file_ext == '.json' else \
                        "텍스트" if file_ext in ['.txt', '.lang', '.md'] else "바이너리"
            
            file_list.append({
                "파일명": name,
                "크기 (bytes)": len(content),
                "타입": file_type
            })
        
        st.dataframe(file_list, use_container_width=True)
        
        # 인코딩 버튼
        if st.button("BRArchive로 인코딩", type="primary"):
            try:
                with st.spinner("파일을 인코딩하는 중..."):
                    archive_data = encode_brarchive(files_dict)
                
                st.success(f"✅ 인코딩 완료! (파일 수: {len(files_dict)}, 크기: {len(archive_data):,} bytes)")
                
                # 인코딩 정보 표시
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.metric("원본 파일 수", len(files_dict))
                    st.metric("아카이브 크기", f"{len(archive_data):,} bytes")
                with col_info2:
                    total_original = sum(len(c) for c in files_dict.values())
                    compression_ratio = (1 - len(archive_data) / total_original) * 100 if total_original > 0 else 0
                    st.metric("원본 총 크기", f"{total_original:,} bytes")
                    st.metric("압축률", f"{compression_ratio:.1f}%")
                
                # 다운로드 버튼
                st.markdown("---")
                archive_name = st.text_input("아카이브 파일명", value="archive.brarchive", key="archive_name")
                if not archive_name.endswith('.brarchive'):
                    archive_name += '.brarchive'
                
                st.download_button(
                    label="BRArchive 파일 다운로드",
                    data=archive_data,
                    file_name=archive_name,
                    mime="application/octet-stream"
                )
                
                # 인코딩 과정 설명
                with st.expander("인코딩 과정 설명"):
                    st.markdown("""
                    **BRArchive 인코딩 구조:**
                    
                    1. **헤더 (16 bytes)**
                       - Magic Number (8 bytes): `0x267052A0B125277D`
                       - Entries Count (4 bytes): 파일 개수
                       - Version (4 bytes): 버전 번호 (현재: 1)
                    
                    2. **엔트리 디스크립터 영역**
                       - 각 파일마다 256 bytes:
                         - Name Length (1 byte)
                         - File Name (247 bytes, 패딩 포함)
                         - Contents Offset (4 bytes): 콘텐츠 영역에서의 오프셋
                         - Contents Length (4 bytes): 파일 크기
                    
                    3. **콘텐츠 영역**
                       - 모든 파일의 실제 데이터가 순서대로 저장됨
                    
                    **이미지 인코딩:**
                    - 이미지 파일은 바이너리 데이터로 그대로 저장됩니다
                    - 압축 없이 원본 크기 그대로 저장됩니다
                    - 여러 이미지를 하나의 .brarchive 파일로 묶을 수 있습니다
                    """)
                
            except Exception as e:
                st.error(f"❌ 인코딩 오류: {str(e)}")
                st.exception(e)
    else:
        st.info("👆 위에서 인코딩할 파일들을 업로드하세요")
        
        with st.expander("ℹ인코딩 정보"):
            st.markdown("""
            **BRArchive 인코딩이란?**
            
            여러 파일을 하나의 .brarchive 파일로 묶는 과정입니다.
            
            **특징:**
            - 압축 없이 원본 데이터를 그대로 저장
            - 이미지, 텍스트, JSON 등 모든 파일 타입 지원
            - Minecraft Bedrock Edition에서 사용하는 표준 포맷
            
            **사용 예시:**
            - 여러 텍스처 이미지를 하나의 아카이브로 묶기
            - 게임 리소스 파일들을 패키징
            - 여러 설정 파일을 하나로 묶기
            """)


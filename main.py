import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from xml.etree import ElementTree as ET

# ====================== 配置区 ======================
QQ_EMAIL = "441466317@qq.com"
QQ_AUTH_CODE = os.environ.get("QQ_AUTH_CODE")          # 从GitHub Secrets读取
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")      # 从GitHub Secrets读取
RECEIVER_EMAIL = "441466317@qq.com"

# PubMed 搜索关键词（细胞免疫治疗相关）
PUBMED_QUERY = (
    '(CAR-T OR "CAR T" OR "chimeric antigen receptor" OR "TCR-T" OR '
    '"TIL" OR "tumor infiltrating lymphocyte" OR "CAR-NK" OR '
    '"adoptive cell therapy" OR "cellular immunotherapy" OR '
    '"engineered T cell" OR "CAR T-cell")'
)

def search_pubmed(query, reldate=3, retmax=12):
    """搜索最近几天的相关论文"""
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": query,
        "reldate": reldate,          # 最近几天
        "datetype": "edat",
        "retmax": retmax,
        "sort": "pub date",
        "retmode": "json",
        "email": QQ_EMAIL,
        "tool": "cell-immunotherapy-daily"
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("esearchresult", {}).get("idlist", [])

def fetch_papers(pmids):
    """根据PMID获取论文详细信息"""
    if not pmids:
        return []
    
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "email": QQ_EMAIL,
        "tool": "cell-immunotherapy-daily"
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    
    root = ET.fromstring(resp.content)
    papers = []
    
    for article in root.findall(".//PubmedArticle"):
        try:
            title = article.findtext(".//ArticleTitle") or "无标题"
            abstract = " ".join([t.text or "" for t in article.findall(".//AbstractText")]) or "无摘要"
            journal = article.findtext(".//Journal/Title") or "未知期刊"
            pub_date = article.findtext(".//PubDate/Year") or ""
            month = article.findtext(".//PubDate/Month") or ""
            day = article.findtext(".//PubDate/Day") or ""
            date_str = f"{pub_date}-{month}-{day}".strip("-")
            
            pmid = article.findtext(".//PMID")
            doi = None
            for id_node in article.findall(".//ArticleId"):
                if id_node.get("IdType") == "doi":
                    doi = id_node.text
                    break
            
            link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
            
            papers.append({
                "title": title.strip(),
                "abstract": abstract.strip()[:1500],
                "journal": journal,
                "date": date_str,
                "pmid": pmid,
                "doi": doi,
                "link": link
            })
        except Exception:
            continue
    
    return papers

def summarize_with_gemini(papers):
    """用 Gemini 生成中文日报总结"""
    if not papers:
        return "今天没有检索到新的细胞免疫治疗相关论文。"
    
    papers_text = ""
    for i, p in enumerate(papers, 1):
        papers_text += f"""
【论文{i}】
标题：{p['title']}
期刊：{p['journal']}
日期：{p['date']}
链接：{p['link']}
摘要：{p['abstract']}
"""
    
    prompt = f"""
你是一名专业的细胞免疫治疗（CAR-T、TCR-T、TIL、CAR-NK等）领域科研助手。
请根据以下最新论文，生成一份简洁、专业的中文【细胞免疫治疗每日学术进展】。

要求：
1. 用中文输出
2. 筛选出真正相关且有价值的论文（过滤掉不太相关的）
3. 每篇用简洁的语言总结核心发现 + 临床/科研意义
4. 格式清晰，方便快速阅读
5. 最后给出今日整体简评（1-2句话）
6. 如果有重要临床进展或新技术，请重点标注

论文列表：
{papers_text}
"""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    # 如果上面的模型不可用，可改成 gemini-1.5-flash 或 gemini-2.0-flash-lite
    
    headers = {"Content-Type": "application/json"}
    data = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 2048
        }
    }
    
    resp = requests.post(url, headers=headers, json=data, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return "总结生成失败，请检查 Gemini API Key 是否有效。"

def send_email(subject, content):
    """发送邮件"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = QQ_EMAIL
    msg["To"] = RECEIVER_EMAIL
    
    # 纯文本 + 简单HTML
    text_part = MIMEText(content, "plain", "utf-8")
    html_content = content.replace("\n", "<br>")
    html_part = MIMEText(f"<html><body style='font-family: sans-serif; line-height:1.6;'>{html_content}</body></html>", "html", "utf-8")
    
    msg.attach(text_part)
    msg.attach(html_part)
    
    with smtplib.SMTP_SSL("smtp.qq.com", 465) as server:
        server.login(QQ_EMAIL, QQ_AUTH_CODE)
        server.sendmail(QQ_EMAIL, [RECEIVER_EMAIL], msg.as_string())

def main():
    print("开始抓取细胞免疫治疗最新论文...")
    pmids = search_pubmed(PUBMED_QUERY, reldate=3, retmax=12)
    print(f"找到 {len(pmids)} 篇候选论文")
    
    papers = fetch_papers(pmids)
    print(f"成功获取 {len(papers)} 篇详细信息")
    
    print("正在用AI生成中文总结...")
    summary = summarize_with_gemini(papers)
    
    today = datetime.now().strftime("%Y年%m月%d日")
    subject = f"【细胞免疫治疗日报】{today}"
    
    full_content = f"""细胞免疫治疗每日学术进展
日期：{today}

{summary}

——————————————
本邮件由自动程序生成
数据来源：PubMed
"""
    
    print("正在发送邮件...")
    send_email(subject, full_content)
    print("邮件发送成功！")

if __name__ == "__main__":
    main()

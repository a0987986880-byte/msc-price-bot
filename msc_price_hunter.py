import os
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ================= 申訴舉證與 LINE 通知設定 =================
TARGET_TOTAL_USD = 2000.0   # 你的雙人含稅總價 (美金)
SAVE_DIR = "完成"           # 儲存舉證截圖資料夾

# 從環境變數讀取金鑰 (本機測試也可直接把字串貼在第二個引號內)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "貼上你的_Channel_Access_Token")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "貼上你的_User_ID")

MSC_USA_URL = "https://www.msccruisesusa.com/Search%20Result?embarkationPort=KEL&departureDateFrom=09%2F01%2F2027&departureDateTo=09%2F01%2F2027&passengers=2%7C0%7C0%7C0"
CRUISE_COM_URL = "https://www.cruise.com/cruise-lines/msc-cruises/msc-bellissima/"
CRUISEDIRECT_URL = "https://www.cruisedirect.com/cruise-line/msc-cruises/msc-bellissima"
# ============================================================

os.makedirs(SAVE_DIR, exist_ok=True)

def send_line_alert(message: str):
    """透過 LINE Messaging API 發送推播通知"""
    print(f"\n[LINE 推播發送]\n{message}\n")
    if not LINE_CHANNEL_ACCESS_TOKEN.startswith("貼上"):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        payload = {
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": message}]
        }
        resp = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
        if resp.status_code != 200:
            print(f"[LINE 發送失敗] 狀態碼: {resp.status_code}, 原因: {resp.text}")

def check_msc_usa_deep(page, now_str: str):
    """深度掃描 MSC 美國官網內艙含稅總價"""
    print("  [1/3] 正在掃描 MSC 美國官網...")
    try:
        page.goto(MSC_USA_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        for selector in ["button:has-text('Accept')", "button:has-text('Agree')", "#onetrust-accept-btn-handler"]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        select_btns = page.locator("button:has-text('Select'), a:has-text('Select'), button:has-text('View Prices')").all()
        if select_btns:
            select_btns[0].click()
            page.wait_for_timeout(6000)

        interior_card = page.locator("text=/Interior/i").first
        if interior_card.is_visible():
            interior_card.click()
            page.wait_for_timeout(4000)

        body_text = page.inner_text("body")
        total_matches = re.findall(r'(?:Total|Total Price|Grand Total)[^\d\$]{0,15}\$\s?(\d{3,4}(?:,\d{3})?(?:\.\d{2})?)', body_text, re.IGNORECASE)
        if total_matches:
            prices = [float(m.replace(',', '')) for m in total_matches if 550 <= float(m.replace(',', '')) <= 2000]
        else:
            all_matches = re.findall(r'\$\s?(\d{3,4}(?:,\d{3})?(?:\.\d{2})?)', body_text)
            prices = [float(m.replace(',', '')) for m in all_matches if 550 <= float(m.replace(',', '')) <= 2000]

        if prices:
            lowest_total = min(prices)
            print(f"    -> MSC 美國官網偵測雙人總價: ${lowest_total:.2f} USD")
            if lowest_total < TARGET_TOTAL_USD:
                img_path = os.path.join(SAVE_DIR, f"MSC_USA_Total_{lowest_total}_{now_str}.png")
                page.screenshot(path=img_path, full_page=True)
                send_line_alert(
                    f"🎯 MSC 美國官網確定降價！\n"
                    f"偵測雙人總價：${lowest_total:.2f} USD（低於你的 ${TARGET_TOTAL_USD}）\n"
                    f"舉證截圖已自動存檔，請立刻點下方連結截圖結帳總價頁並聯絡 MSC USA 客服：\n"
                    f"{page.url}"
                )
        else:
            print("    -> MSC 美國官網未抓到 >$550 總價")

    except Exception as e:
        print(f"    -> MSC 美國官網掃描異常: {e}")

def check_us_agencies(page, now_str: str):
    """掃描美國正式持牌郵輪旅行社"""
    agencies = [
        ("Cruise.com (美國官方代理)", CRUISE_COM_URL),
        ("CruiseDirect (美國大型代理)", CRUISEDIRECT_URL),
    ]

    for idx, (name, url) in enumerate(agencies, start=2):
        print(f"  [{idx}/3] 正在掃描 {name}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)

            try:
                filter_2027 = page.locator("text=/Jan.*2027|2027/i").first
                if filter_2027.is_visible():
                    filter_2027.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

            body_text = page.inner_text("body")
            matches = re.findall(r'\$\s?(\d{3,4}(?:,\d{3})?)', body_text)
            per_person_prices = [float(m.replace(',', '')) for m in matches if 250 <= float(m.replace(',', '')) <= 800]

            if per_person_prices:
                lowest_pp = min(per_person_prices)
                est_total = (lowest_pp * 2) + 240
                print(f"    -> {name} 單人起價: ${lowest_pp:.0f} (含稅預估雙人約 ${est_total:.0f})")

                if est_total < TARGET_TOTAL_USD:
                    img_path = os.path.join(SAVE_DIR, f"Agency_{lowest_pp}pp_{now_str}.png")
                    page.screenshot(path=img_path, full_page=True)
                    send_line_alert(
                        f"🚨 {name} 出現超低清倉價！\n"
                        f"單人起價僅 ${lowest_pp:.0f} USD（含稅預估雙人約 ${est_total:.0f} USD，低於你的 ${TARGET_TOTAL_USD}）！\n"
                        f"請立刻點進連結確認並截圖：\n"
                        f"{url}"
                    )
            else:
                print(f"    -> {name} 未偵測到目標航次報價")

        except Exception as e:
            print(f"    -> {name} 掃描異常: {e}")

def main():
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    print(f"\n==================== [{now_str}] 開始執行跨平台比價 ====================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        check_msc_usa_deep(page, now_str)
        check_us_agencies(page, now_str)

        browser.close()
    print("==================== 本次巡檢結束 ====================\n")

if __name__ == "__main__":
    main()

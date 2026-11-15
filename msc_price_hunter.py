import os
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ================= 申訴舉證與 LINE 通知設定 =================
TARGET_TOTAL_USD = 2000.0   # 你的雙人含稅總價 (美金)
SAVE_DIR = "完成"           # 儲存舉證截圖資料夾

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# 1. MSC 美國官網：直接鎖定 2027/01 基隆 (KEL) 出發、2 位大人搜尋結果頁
MSC_USA_URL = "https://www.msccruisesusa.com/Search%20Result?embarkationPort=KEL&departureDateFrom=01%2F01%2F2027&departureDateTo=31%2F01%2F2027&passengers=2%7C0%7C0%7C0"

# 2. Cruise.com：鎖定 MSC Bellissima 2027 年 1 月航程查詢頁
CRUISE_COM_URL = "https://www.cruise.com/search/?cruiseline=12&ship=538&month=2027-01"

# 3. CruiseDirect：鎖定 MSC Bellissima 2027 年 1 月亞洲航線查詢頁
CRUISEDIRECT_URL = "https://www.cruisedirect.com/search?cruise_line=msc-cruises&ship=msc-bellissima&departure_month=2027-01"
# ============================================================

os.makedirs(SAVE_DIR, exist_ok=True)

def send_line_alert(message: str):
    """透過 LINE Messaging API 發送推播通知"""
    print(f"\n[嘗試發送 LINE 推播]\n{message}\n")
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[錯誤] 讀取不到 GitHub Secrets 的 LINE 金鑰！")
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN.strip()}"
    }
    payload = {
        "to": LINE_USER_ID.strip(),
        "messages": [{"type": "text", "text": message}]
    }
    resp = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=payload)
    if resp.status_code == 200:
        print("[成功] LINE 訊息已成功送出！")
    else:
        print(f"[LINE 發送失敗] 狀態碼: {resp.status_code}, 原因: {resp.text}")

def scroll_and_wait(page):
    """模擬真人往下滑動網頁，觸發延遲載入的價格卡片"""
    for _ in range(3):
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(1500)

def check_msc_usa_deep(page, now_str: str):
    print("  [1/3] 正在深度掃描 MSC 美國官網 (2027/01 基隆出發)...")
    try:
        page.goto(MSC_USA_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)
        scroll_and_wait(page)

        for selector in ["button:has-text('Accept')", "button:has-text('Agree')", "#onetrust-accept-btn-handler"]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                pass

        # 尋找 2027/01/09 航次的選擇按鈕
        select_btns = page.locator("button:has-text('Select'), a:has-text('Select'), button:has-text('View Prices'), button:has-text('Book')").all()
        if select_btns:
            select_btns[0].click()
            page.wait_for_timeout(7000)
            scroll_and_wait(page)

        interior_card = page.locator("text=/Interior/i").first
        if interior_card.is_visible():
            interior_card.click()
            page.wait_for_timeout(5000)

        # 保存當下巡檢畫面至 GitHub Artifacts 供下載檢查
        debug_img = os.path.join(SAVE_DIR, f"Check_MSC_USA_{now_str}.png")
        page.screenshot(path=debug_img, full_page=True)

        body_text = page.inner_text("body")
        all_matches = re.findall(r'\$\s?(\d{3,4}(?:,\d{3})?(?:\.\d{2})?)', body_text)
        raw_nums = [float(m.replace(',', '')) for m in all_matches if 200 <= float(m.replace(',', '')) <= 2500]
        print(f"    -> MSC 美國官網抓到的美金數字: {sorted(list(set(raw_nums)))}")

        # 若列表頁顯示單人價 (約 $300~$450) 或總價 (約 $600~$1500)，雙重判斷
        total_prices = [p for p in raw_nums if p >= 550]
        pp_prices = [p for p in raw_nums if 250 <= p < 550]

        if total_prices:
            lowest_total = min(total_prices)
            print(f"    -> 判定雙人總價: ${lowest_total:.2f} USD")
            if lowest_total < TARGET_TOTAL_USD:
                send_line_alert(
                    f"🎯 MSC 美國官網確定降價！\n"
                    f"偵測雙人總價：${lowest_total:.2f} USD（低於你的 ${TARGET_TOTAL_USD}）\n"
                    f"請立刻點下方連結截圖結帳總價頁：\n{page.url}"
                )
        elif pp_prices:
            lowest_pp = min(pp_prices)
            est_total = (lowest_pp * 2) + 220
            print(f"    -> 偵測單人起價: ${lowest_pp:.2f} USD (含稅預估雙人約 ${est_total:.2f})")
            if est_total < TARGET_TOTAL_USD:
                send_line_alert(
                    f"🎯 MSC 美國官網疑似降價！\n"
                    f"單人起價 ${lowest_pp:.2f} USD（含稅預估雙人約 ${est_total:.2f} USD），請點進確認：\n{page.url}"
                )
        else:
            print("    -> MSC 美國官網仍未顯示價格數字（建議下載 GitHub Artifacts 截圖查看畫面）")

    except Exception as e:
        print(f"    -> MSC 美國官網掃描異常: {e}")

def check_us_agencies(page, now_str: str):
    agencies = [
        ("Cruise.com (美國官方代理)", CRUISE_COM_URL),
        ("CruiseDirect (美國大型代理)", CRUISEDIRECT_URL),
    ]

    for idx, (name, url) in enumerate(agencies, start=2):
        print(f"  [{idx}/3] 正在掃描 {name}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            scroll_and_wait(page)

            # 存一張代理商畫面截圖方便核對
            agency_img = os.path.join(SAVE_DIR, f"Check_Agency_{idx}_{now_str}.png")
            page.screenshot(path=agency_img, full_page=True)

            body_text = page.inner_text("body")
            matches = re.findall(r'\$\s?(\d{3,4}(?:,\d{3})?)', body_text)
            per_person_prices = [float(m.replace(',', '')) for m in matches if 200 <= float(m.replace(',', '')) <= 900]
            print(f"    -> {name} 抓到的價格數字: {sorted(list(set(per_person_prices)))}")

            if per_person_prices:
                lowest_pp = min(per_person_prices)
                est_total = (lowest_pp * 2) + 220
                print(f"    -> {name} 單人起價: ${lowest_pp:.0f} (含稅預估雙人約 ${est_total:.0f})")

                if est_total < TARGET_TOTAL_USD:
                    send_line_alert(
                        f"🚨 {name} 出現超低清倉價！\n"
                        f"單人起價僅 ${lowest_pp:.0f} USD（含稅預估雙人約 ${est_total:.0f} USD，低於你的 ${TARGET_TOTAL_USD}）！\n"
                        f"請立刻點進連結確認並截圖：\n{url}"
                    )
            else:
                print(f"    -> {name} 未偵測到價格數字")

        except Exception as e:
            print(f"    -> {name} 掃描異常: {e}")

def main():
    now_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
    print(f"\n==================== [{now_str}] 開始執行跨平台比價 ====================")

    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        send_line_alert(f"🤖 測試連線成功！MSC 雲端比價機器人已開始掃描 2027/01 基隆航次（目前門檻：${TARGET_TOTAL_USD} USD）。")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()

        check_msc_usa_deep(page, now_str)
        check_us_agencies(page, now_str)

        browser.close()
    print("==================== 本次巡檢結束 ====================\n")

if __name__ == "__main__":
    main()

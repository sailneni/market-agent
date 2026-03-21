import http.cookiejar
import os

COOKIES_FILE = "cookies.txt"

def verify_cookies():
    if not os.path.exists(COOKIES_FILE):
        print("❌ cookies.txt not found")
        return

    # Check Netscape header
    with open(COOKIES_FILE, "r") as f:
        first_line = f.readline().strip()
        if "Netscape HTTP Cookie File" not in first_line:
            print(f"❌ Invalid format — first line should be '# Netscape HTTP Cookie File', got: '{first_line}'")
        else:
            print("✅ Netscape format header found")

    # Try loading via cookiejar
    try:
        cj = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
        cj.load(ignore_discard=True, ignore_expires=True)
        cookies = list(cj)
        print(f"✅ Loaded {len(cookies)} cookies")

        # Check for key YouTube auth cookies
        youtube_keys = ["SAPISID", "__Secure-3PAPISID", "SID", "HSID", "LOGIN_INFO"]
        found_keys = [c.name for c in cookies if c.name in youtube_keys]
        missing_keys = [k for k in youtube_keys if k not in found_keys]

        print(f"✅ YouTube auth cookies found : {found_keys}")
        if missing_keys:
            print(f"⚠️  Missing key cookies       : {missing_keys}")
        else:
            print("✅ All key YouTube cookies present")

        # Check domains
        yt_cookies = [c for c in cookies if "youtube" in c.domain or "google" in c.domain]
        print(f"✅ YouTube/Google domain cookies: {len(yt_cookies)}")

    except Exception as e:
        print(f"❌ Failed to load cookies: {e}")

verify_cookies()

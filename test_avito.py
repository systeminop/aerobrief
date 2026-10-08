def test_avito():
    print("===== AVITO TEST START =====")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
        )
    }

    try:
        response = requests.get(
            AVITO_URL,
            headers=headers,
            timeout=20
        )

        print("AVITO STATUS:", response.status_code)
        print("AVITO LENGTH:", len(response.text))

        text = response.text

        print("RIO COUNT:", text.lower().count("kia rio"))
        print("PRICE COUNT:", text.count("700000"))

        print("===== AVITO RESPONSE START =====")
        print(text[:500])
        print("===== AVITO RESPONSE END =====")

    except Exception as e:
        print("AVITO ERROR:", repr(e))

    print("===== AVITO TEST END =====")

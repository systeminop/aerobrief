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

        # Ищем признаки структурированных данных
        markers = [
            "__NEXT_DATA__",
            "itemId",
            "item_id",
            "price",
            "mileage",
            "vehicle",
            "year",
            "location",
            "title"
        ]

        print("===== DATA MARKERS =====")

        for marker in markers:
            count = text.lower().count(marker.lower())
            print(f"{marker}: {count}")

        # Показываем куски HTML вокруг itemId
        print("===== ITEM DATA SAMPLES =====")

        search_marker = "itemId"
        positions = []

        start = 0

        while True:
            position = text.find(search_marker, start)

            if position == -1:
                break

            positions.append(position)
            start = position + len(search_marker)

            if len(positions) >= 5:
                break

        print("ITEMID POSITIONS:", positions)

        for index, position in enumerate(positions, start=1):
            print(f"===== SAMPLE {index} =====")

            sample_start = max(0, position - 500)
            sample_end = min(
                len(text),
                position + 1500
            )

            print(text[sample_start:sample_end])

        print("===== AVITO TEST END =====")

    except Exception as e:
        print("AVITO ERROR:", repr(e))

    print("===== AVITO TEST FINISHED =====")

from flask import Flask, jsonify, request, render_template_string
import requests
import time
import re

from datetime import datetime, timedelta
from html import unescape


# =========================================================
# Flask
# =========================================================

app = Flask(__name__)


# =========================================================
# API設定
# =========================================================

API_BASE = "https://result.swim.or.jp/api/v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# =========================================================
# JO公式ページ
# =========================================================

JO_STANDARD_URL = (
    "https://aquatics.or.jp/swim/japan_record/2026/05/"
)

JO_REFERENCE_DATE = datetime(2026, 8, 22)


# =========================================================
# マスターデータ
# =========================================================

WATERWAYS = {
    1: "長水路",
    2: "短水路",
}

STYLES = {
    1: "自由形",
    2: "背泳ぎ",
    3: "平泳ぎ",
    4: "バタフライ",
    5: "個人メドレー",
}

DISTANCES = {
    2: "50m",
    3: "100m",
    4: "200m",
    5: "400m",
    6: "800m",
    7: "1500m",
}

PERIODS = {
    1: "直近6ヶ月",
    2: "2026年度",
    3: "2025年度以降",
    4: "2024年度以降",
}


# =========================================================
# 共通関数
# =========================================================

def swimmer_code_to_athlete_id(swimmer_code):
    return 3 * (int(swimmer_code) + 10_000_000) + 3


def unwrap_value(value):

    if isinstance(value, dict):

        for key in (
            "name",
            "label",
            "value",
            "text",
        ):

            if key in value:
                return value[key]

    return value


def normalize_gender(value):

    value = unwrap_value(value)

    if value is None:
        return ""

    text = str(value)

    if (
        "男子" in text
        or text.lower() in ("male", "man", "m")
    ):
        return "男子"

    if (
        "女子" in text
        or text.lower() in ("female", "woman", "f")
    ):
        return "女子"

    return text


def time_to_seconds(time_text):

    if time_text is None:
        return None

    text = str(time_text).strip()

    if not text:
        return None

    text = text.replace(",", ".")

    try:

        if ":" in text:

            parts = text.split(":")

            if len(parts) == 2:

                minutes = float(parts[0])
                seconds = float(parts[1])

                return minutes * 60 + seconds

            if len(parts) == 3:

                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])

                return (
                    hours * 3600
                    + minutes * 60
                    + seconds
                )

        return float(text)

    except Exception:
        return None


def seconds_to_time(seconds):

    if seconds is None:
        return ""

    try:
        seconds = float(seconds)

    except Exception:
        return ""

    minutes = int(seconds // 60)

    remaining = seconds - minutes * 60

    if minutes > 0:
        return f"{minutes}:{remaining:05.2f}"

    return f"{remaining:.2f}"


def parse_date(value):

    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()

    if not text:
        return None

    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y年%m月%d日",
    ]

    for fmt in formats:

        try:

            return datetime.strptime(
                text[:26],
                fmt
            )

        except Exception:
            pass

    return None


def calculate_age(
    birth_date,
    reference_date
):

    if birth_date is None:
        return None

    if isinstance(birth_date, str):

        birth_date = parse_date(
            birth_date
        )

    if birth_date is None:
        return None

    age = (
        reference_date.year
        - birth_date.year
    )

    if (
        reference_date.month,
        reference_date.day
    ) < (
        birth_date.month,
        birth_date.day
    ):

        age -= 1

    return age


# =========================================================
# Swim API
# =========================================================

class SwimAPI:

    def __init__(self):

        self.session = requests.Session()

        self.session.headers.update(
            HEADERS
        )

        self.last_request_time = 0.0

        self.min_request_interval = 0.05

    def get(
        self,
        endpoint,
        params=None
    ):

        url = API_BASE + endpoint

        print()
        print("======================================")
        print("API REQUEST")
        print(url)

        if params:
            print("PARAMS:", params)

        print("======================================")

        for attempt in range(3):

            elapsed = (
                time.time()
                - self.last_request_time
            )

            if elapsed < self.min_request_interval:

                time.sleep(
                    self.min_request_interval
                    - elapsed
                )

            try:

                response = self.session.get(
                    url,
                    params=params,
                    timeout=15,
                )

                self.last_request_time = time.time()

                print(
                    "STATUS:",
                    response.status_code
                )

                if response.status_code == 429:

                    wait_time = (
                        3 * (attempt + 1)
                    )

                    print(
                        "429 Too Many Requests "
                        f"→ {wait_time}秒待機"
                    )

                    time.sleep(
                        wait_time
                    )

                    continue

                response.raise_for_status()

                return response.json()

            except Exception as e:

                print(
                    f"API ERROR attempt={attempt + 1}:",
                    repr(e)
                )

                if attempt < 2:
                    time.sleep(2)

        return None

    def search_athletes(
        self,
        name
    ):

        results = []

        seen = set()

        for gender_code in (
            1,
            2,
            3
        ):

            data = self.get(
                "/athletes",
                params={
                    "name": name,
                    "school_class_code": 99,
                    "gender_code": gender_code,
                },
            )

            if not data:
                continue

            print(
                "SEARCH RAW:",
                data
            )

            candidates = []

            if isinstance(
                data,
                dict
            ):

                for key in (
                    "data",
                    "results",
                    "items",
                    "athletes",
                ):

                    value = data.get(key)

                    if isinstance(
                        value,
                        list
                    ):

                        candidates = value
                        break

            elif isinstance(
                data,
                list
            ):

                candidates = data

            for athlete in candidates:

                if not isinstance(
                    athlete,
                    dict
                ):
                    continue

                swimmer_code = (
                    athlete.get(
                        "swimmer_code"
                    )
                    or athlete.get(
                        "swimmerCode"
                    )
                    or athlete.get(
                        "code"
                    )
                )

                athlete_id = (
                    athlete.get("id")
                    or athlete.get(
                        "athlete_id"
                    )
                    or athlete.get(
                        "athleteId"
                    )
                )

                unique_key = (
                    swimmer_code
                    or athlete_id
                )

                if unique_key in seen:
                    continue

                seen.add(
                    unique_key
                )

                results.append(
                    athlete
                )

        return results

    def get_athlete(
        self,
        athlete_id
    ):

        return self.get(
            f"/athletes/{athlete_id}"
        )

    def get_records(
        self,
        athlete_id,
        waterway_code,
        style_code,
        distance_code,
    ):

        endpoint = (
            f"/athletes/{athlete_id}"
            f"/results/waterways/{waterway_code}"
            f"/swimming_styles/{style_code}"
            f"/distances/{distance_code}/records"
        )

        data = self.get(
            endpoint,
            params={
                "period_code": 4
            },
        )

        if not data:
            return []

        records = []

        if isinstance(
            data,
            dict
        ):

            raw_records = (
                data.get("result")
                or data.get("data")
                or data.get("records")
                or data.get("items")
                or []
            )

        elif isinstance(
            data,
            list
        ):

            raw_records = data

        else:

            raw_records = []

        for item in raw_records:

            if not isinstance(
                item,
                dict
            ):
                continue

            if (
                "year" in item
                and isinstance(
                    item.get("data"),
                    list
                )
            ):

                year = item.get(
                    "year"
                )

                for record in item["data"]:

                    if isinstance(
                        record,
                        dict
                    ):

                        record = record.copy()

                        record["_year"] = year

                        record[
                            "_waterway_code"
                        ] = waterway_code

                        record[
                            "_style_code"
                        ] = style_code

                        record[
                            "_distance_code"
                        ] = distance_code

                        records.append(
                            record
                        )

            else:

                record = item.copy()

                record[
                    "_waterway_code"
                ] = waterway_code

                record[
                    "_style_code"
                ] = style_code

                record[
                    "_distance_code"
                ] = distance_code

                records.append(
                    record
                )

        return records

    def get_all_records(
        self,
        athlete_id
    ):

        all_records = []

        for waterway_code in WATERWAYS:

            for style_code in STYLES:

                for distance_code in DISTANCES:

                    records = self.get_records(
                        athlete_id,
                        waterway_code,
                        style_code,
                        distance_code,
                    )

                    all_records.extend(
                        records
                    )

        return all_records


# =========================================================
# JO Standard
# =========================================================

class JOStandardScraper:

    def __init__(self):

        self.url = JO_STANDARD_URL

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": HEADERS[
                "User-Agent"
            ],
            "Accept":
                "text/html,"
                "application/xhtml+xml",
        })

        self.standards = {}

    def fetch_html(self):

        response = self.session.get(
            self.url,
            timeout=20
        )

        response.raise_for_status()

        return response.text

    @staticmethod
    def clean_html(text):

        text = re.sub(
            r"<[^>]+>",
            " ",
            text
        )

        text = unescape(
            text
        )

        text = text.replace(
            "\xa0",
            " "
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    @staticmethod
    def normalize_time(text):

        if text is None:
            return None

        text = str(text).strip()

        if not text:
            return None

        if text in (
            "-",
            "—",
            "―",
            "-----",
            "なし",
        ):
            return None

        return time_to_seconds(
            text
        )

    @staticmethod
    def age_category(age):

        if age is None:
            return None

        if age <= 9:
            return "9歳以下"

        if age == 10:
            return "10歳"

        if age == 11:
            return "11歳"

        if age == 12:
            return "12歳"

        if age == 13:
            return "13歳"

        if age == 14:
            return "14歳"

        if age in (15, 16):
            return "15~16歳"

        if age >= 17:
            return "CS"

        return None

    @staticmethod
    def normalize_age_category(text):

        text = str(text).strip()

        text = text.replace(
            "～",
            "~"
        )

        text = text.replace(
            "〜",
            "~"
        )

        if "9歳以下" in text:
            return "9歳以下"

        if text == "10歳":
            return "10歳"

        if text == "11歳":
            return "11歳"

        if text == "12歳":
            return "12歳"

        if text == "13歳":
            return "13歳"

        if text == "14歳":
            return "14歳"

        if (
            "15" in text
            and "16" in text
        ):
            return "15~16歳"

        if text == "CS":
            return "CS"

        return None

    @staticmethod
    def parse_event_title(text):

        text = text.strip()

        style = None

        if "自由形" in text:
            style = "自由形"

        elif "背泳ぎ" in text:
            style = "背泳ぎ"

        elif "平泳ぎ" in text:
            style = "平泳ぎ"

        elif "バタフライ" in text:
            style = "バタフライ"

        elif "個人メドレー" in text:
            style = "個人メドレー"

        if style is None:
            return None

        match = re.search(
            r"(\d+)\s*m",
            text
        )

        if not match:
            return None

        distance = int(
            match.group(1)
        )

        if distance == 25:
            return None

        return style, distance

    def parse_tables(
        self,
        html
    ):

        from bs4 import BeautifulSoup

        standards = {}

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        headings = soup.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4"
            ]
        )

        for heading in headings:

            title = heading.get_text(
                " ",
                strip=True
            )

            event = self.parse_event_title(
                title
            )

            if event is None:
                continue

            style, distance = event

            table = heading.find_next(
                "table"
            )

            if table is None:
                continue

            rows = table.find_all(
                "tr"
            )

            for row in rows:

                cells = row.find_all(
                    [
                        "th",
                        "td"
                    ]
                )

                values = [
                    self.clean_html(
                        cell.decode_contents()
                    )
                    for cell in cells
                ]

                if len(values) < 5:
                    continue

                age_category = (
                    self.normalize_age_category(
                        values[0]
                    )
                )

                if age_category is None:
                    continue

                boys_short = (
                    self.normalize_time(
                        values[1]
                    )
                )

                boys_long = (
                    self.normalize_time(
                        values[2]
                    )
                )

                girls_short = (
                    self.normalize_time(
                        values[3]
                    )
                )

                girls_long = (
                    self.normalize_time(
                        values[4]
                    )
                )

                entries = [
                    (
                        "男子",
                        "短水路",
                        boys_short
                    ),
                    (
                        "男子",
                        "長水路",
                        boys_long
                    ),
                    (
                        "女子",
                        "短水路",
                        girls_short
                    ),
                    (
                        "女子",
                        "長水路",
                        girls_long
                    ),
                ]

                for (
                    gender,
                    waterway,
                    seconds
                ) in entries:

                    if seconds is None:
                        continue

                    standards[
                        (
                            style,
                            distance,
                            age_category,
                            gender,
                            waterway,
                        )
                    ] = seconds

        return standards

    def update(self):

        html = self.fetch_html()

        standards = self.parse_tables(
            html
        )

        if not standards:

            raise RuntimeError(
                "公式サイトからJO標準記録を取得できませんでした。"
            )

        self.standards = standards

        return standards

    def get_standard(
        self,
        style,
        distance,
        age,
        gender,
        waterway
    ):

        category = self.age_category(
            age
        )

        if category is None:
            return None

        return self.standards.get(
            (
                style,
                distance,
                category,
                gender,
                waterway,
            )
        )


# =========================================================
# グローバル
# =========================================================

api = SwimAPI()

jo_scraper = JOStandardScraper()

athlete_cache = {}

record_cache = {}


# =========================================================
# 所属名
# =========================================================

def extract_school_name(obj):

    if not isinstance(
        obj,
        dict
    ):
        return ""

    entry_group = obj.get(
        "entry_group"
    )

    if isinstance(
        entry_group,
        dict
    ):

        name = entry_group.get(
            "name"
        )

        if name:
            return str(name)

    for key in (
        "school_name",
        "schoolName",
        "club_name",
        "clubName",
        "team_name",
        "teamName",
        "affiliation_name",
        "affiliationName",
    ):

        value = obj.get(
            key
        )

        if value:

            value = unwrap_value(
                value
            )

            if value:
                return str(value)

    return ""


# =========================================================
# 生年月日
# =========================================================

def extract_birth_date(obj):

    if isinstance(
        obj,
        dict
    ):

        for key in (
            "birth_date",
            "birthDate",
            "birthday",
            "date_of_birth",
            "dateOfBirth",
            "birthdate",
        ):

            if key in obj:

                parsed = parse_date(
                    obj[key]
                )

                if parsed:
                    return parsed

        for value in obj.values():

            result = extract_birth_date(
                value
            )

            if result:
                return result

    elif isinstance(
        obj,
        list
    ):

        for value in obj:

            result = extract_birth_date(
                value
            )

            if result:
                return result

    return None


# =========================================================
# 記録のフィルター
# =========================================================

def filter_by_period(
    records,
    period
):

    now = datetime.now()

    if period == "直近6ヶ月":

        start_date = (
            now
            - timedelta(days=183)
        )

    elif period == "2026年度":

        start_date = datetime(
            2026,
            4,
            1
        )

    elif period == "2025年度以降":

        start_date = datetime(
            2025,
            4,
            1
        )

    elif period == "2024年度以降":

        start_date = datetime(
            2024,
            4,
            1
        )

    else:

        return records

    result = []

    for record in records:

        date = parse_date(
            record.get(
                "result_date"
            )
        )

        if date and date >= start_date:
            result.append(
                record
            )

    return result


# =========================================================
# 全種目ベスト
# =========================================================

def get_all_bests(
    records,
    period
):

    filtered = filter_by_period(
        records,
        period
    )

    result = {}

    for record in filtered:

        style_code = record.get(
            "_style_code"
        )

        waterway_code = record.get(
            "_waterway_code"
        )

        distance_code = record.get(
            "_distance_code"
        )

        if (
            style_code not in STYLES
            or waterway_code not in WATERWAYS
            or distance_code not in DISTANCES
        ):
            continue

        result_time = time_to_seconds(
            record.get(
                "result_time"
            )
        )

        if result_time is None:
            continue

        key = (
            style_code,
            waterway_code,
            distance_code,
        )

        if key not in result:

            result[key] = record

            continue

        current_time = time_to_seconds(
            result[key].get(
                "result_time"
            )
        )

        if (
            current_time is None
            or result_time < current_time
        ):

            result[key] = record

    return result


# =========================================================
# 記録をWeb用に変換
# =========================================================

def serialize_record(record):

    result_time = time_to_seconds(
        record.get(
            "result_time"
        )
    )

    date = parse_date(
        record.get(
            "result_date"
        )
    )

    return {
        "style": STYLES.get(
            record.get(
                "_style_code"
            ),
            ""
        ),
        "waterway": WATERWAYS.get(
            record.get(
                "_waterway_code"
            ),
            ""
        ),
        "distance": DISTANCES.get(
            record.get(
                "_distance_code"
            ),
            ""
        ),
        "style_code": record.get(
            "_style_code"
        ),
        "waterway_code": record.get(
            "_waterway_code"
        ),
        "distance_code": record.get(
            "_distance_code"
        ),
        "time": seconds_to_time(
            result_time
        ),
        "seconds": result_time,
        "date": (
            date.strftime("%Y-%m-%d")
            if date
            else ""
        ),
        "game": (
            record.get(
                "game_name"
            )
            or record.get(
                "competition_name"
            )
            or ""
        ),
    }


# =========================================================
# TOP
# =========================================================

@app.route("/")
def index():

    return render_template_string(
        HTML
    )


# =========================================================
# 選手検索API
# =========================================================

@app.route(
    "/api/search"
)
def search():

    name = (
        request.args.get(
            "name",
            ""
        )
        .strip()
    )

    if not name:

        return jsonify({
            "error": "選手名を入力してください。"
        }), 400

    try:

        results = api.search_athletes(
            name
        )

        output = []

        for athlete in results:

            output.append({
                "name": (
                    athlete.get(
                        "swimmer_name"
                    )
                    or athlete.get(
                        "swimmerName"
                    )
                    or athlete.get(
                        "name"
                    )
                    or ""
                ),
                "gender": normalize_gender(
                    athlete.get(
                        "gender"
                    )
                    or athlete.get(
                        "gender_name"
                    )
                    or athlete.get(
                        "genderName"
                    )
                    or ""
                ),
                "school": extract_school_name(
                    athlete
                ),
                "swimmer_code": (
                    athlete.get(
                        "swimmer_code"
                    )
                    or athlete.get(
                        "swimmerCode"
                    )
                    or athlete.get(
                        "code"
                    )
                    or ""
                ),
            })

        return jsonify({
            "results": output
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# 選手詳細
# =========================================================

@app.route(
    "/api/athlete/<athlete_id>"
)
def athlete_detail(
    athlete_id
):

    try:

        athlete = api.get_athlete(
            athlete_id
        )

        if not athlete:

            return jsonify({
                "error": "選手情報を取得できませんでした。"
            }), 404

        athlete_cache[
            str(athlete_id)
        ] = athlete

        name = (
            athlete.get(
                "swimmer_name"
            )
            or athlete.get(
                "swimmerName"
            )
            or athlete.get(
                "name"
            )
            or ""
        )

        gender = normalize_gender(
            athlete.get(
                "gender"
            )
            or athlete.get(
                "gender_name"
            )
            or athlete.get(
                "genderName"
            )
            or ""
        )

        school = extract_school_name(
            athlete
        )

        swimmer_code = (
            athlete.get(
                "swimmer_code"
            )
            or athlete.get(
                "swimmerCode"
            )
            or athlete.get(
                "code"
            )
            or ""
        )

        birthday = extract_birth_date(
            athlete
        )

        age = None

        if birthday:

            age = calculate_age(
                birthday,
                JO_REFERENCE_DATE
            )

        return jsonify({
            "name": name,
            "gender": gender,
            "school": school,
            "swimmer_code": swimmer_code,
            "age": age,
            "birthday": (
                birthday.strftime(
                    "%Y-%m-%d"
                )
                if birthday
                else ""
            ),
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# 全記録取得
# =========================================================

@app.route(
    "/api/records/<athlete_id>"
)
def records(
    athlete_id
):

    athlete_id = str(
        athlete_id
    )

    if athlete_id in record_cache:

        return jsonify({
            "records": [
                serialize_record(r)
                for r in record_cache[
                    athlete_id
                ]
            ]
        })

    try:

        all_records = api.get_all_records(
            int(athlete_id)
        )

        record_cache[
            athlete_id
        ] = all_records

        return jsonify({
            "records": [
                serialize_record(r)
                for r in all_records
            ]
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# JO標準取得
# =========================================================

@app.route(
    "/api/jo"
)
def jo():

    try:

        standards = jo_scraper.update()

        output = []

        for (
            key,
            seconds
        ) in standards.items():

            (
                style,
                distance,
                age_category,
                gender,
                waterway,
            ) = key

            output.append({
                "style": style,
                "distance": distance,
                "age_category": age_category,
                "gender": gender,
                "waterway": waterway,
                "seconds": seconds,
                "time": seconds_to_time(
                    seconds
                ),
            })

        return jsonify({
            "standards": output
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# JO比較
# =========================================================

@app.route(
    "/api/jo/compare",
    methods=["POST"]
)
def jo_compare():

    try:

        data = request.get_json()

        athlete_id = str(
            data.get(
                "athlete_id"
            )
        )

        age = int(
            data.get(
                "age"
            )
        )

        gender = data.get(
            "gender"
        )

        period = data.get(
            "period",
            "2024年度以降"
        )

        style_filter = data.get(
            "style",
            "すべて"
        )

        waterway_filter = data.get(
            "waterway",
            "すべて"
        )

        distance_filter = data.get(
            "distance",
            "すべて"
        )

        if athlete_id not in record_cache:

            all_records = api.get_all_records(
                int(athlete_id)
            )

            record_cache[
                athlete_id
            ] = all_records

        all_records = record_cache[
            athlete_id
        ]

        if not jo_scraper.standards:

            jo_scraper.update()

        bests = get_all_bests(
            all_records,
            period
        )

        output = []

        for (
            key,
            record
        ) in bests.items():

            (
                style_code,
                waterway_code,
                distance_code,
            ) = key

            style = STYLES.get(
                style_code
            )

            waterway = WATERWAYS.get(
                waterway_code
            )

            distance = DISTANCES.get(
                distance_code
            )

            if not style:
                continue

            if style_filter != "すべて":

                if style != style_filter:
                    continue

            if waterway_filter != "すべて":

                if waterway != waterway_filter:
                    continue

            if distance_filter != "すべて":

                if distance != distance_filter:
                    continue

            best_seconds = time_to_seconds(
                record.get(
                    "result_time"
                )
            )

            if best_seconds is None:
                continue

            distance_number = int(
                distance.replace(
                    "m",
                    ""
                )
            )

            standard_seconds = (
                jo_scraper.get_standard(
                    style,
                    distance_number,
                    age,
                    gender,
                    waterway,
                )
            )

            if standard_seconds is None:
                continue

            achievement_rate = (
                standard_seconds
                / best_seconds
                * 100
            )

            difference = (
                best_seconds
                - standard_seconds
            )

            if difference > 0:

                status = "JOまであと"

            else:

                status = "JO突破"

            output.append({
                "style": style,
                "waterway": waterway,
                "distance": distance,
                "best": seconds_to_time(
                    best_seconds
                ),
                "standard": seconds_to_time(
                    standard_seconds
                ),
                "difference": (
                    f"あと {difference:.2f}秒"
                    if difference > 0
                    else f"{abs(difference):.2f}秒"
                ),
                "rate": (
                    f"{achievement_rate:.2f}%"
                ),
                "status": status,
                "difference_seconds": difference,
            })

        return jsonify({
            "results": output
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# =========================================================
# HTML
# =========================================================

HTML = r"""
<!DOCTYPE html>

<html lang="ja">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0, viewport-fit=cover"
>

<meta
    name="theme-color"
    content="#07101D"
>

<meta
    name="apple-mobile-web-app-capable"
    content="yes"
>

<meta
    name="apple-mobile-web-app-status-bar-style"
    content="black-translucent"
>

<title>SWIM MANAGER</title>


<style>

/* ======================================================
   基本
   ====================================================== */

* {
    box-sizing: border-box;
}

html {
    scroll-behavior: smooth;
    background: #07101D;
}

body {

    margin: 0;

    background:
        linear-gradient(
            180deg,
            #07101D 0%,
            #091321 100%
        );

    color: #F8FAFC;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "Hiragino Sans",
        "Hiragino Kaku Gothic ProN",
        "Yu Gothic",
        Meiryo,
        Arial,
        sans-serif;

    -webkit-text-size-adjust: 100%;

    padding-bottom:
        env(safe-area-inset-bottom);
}

button,
input,
select {

    font-family: inherit;

    font-size: 16px;
}

button {

    cursor: pointer;

    -webkit-tap-highlight-color:
        transparent;

    touch-action: manipulation;
}


/* ======================================================
   アプリ全体
   ====================================================== */

.app {

    width: 100%;

    max-width: 1500px;

    min-height: 100vh;

    margin: 0 auto;

    padding:
        30px
        max(20px, 4vw)
        70px;
}


/* ======================================================
   ヘッダー
   ====================================================== */

.header {

    display: flex;

    align-items: center;

    justify-content: space-between;

    gap: 20px;

    margin-bottom: 20px;
}

.header-left {

    display: flex;

    align-items: center;

    min-width: 0;
}

.header-accent {

    width: 5px;

    height: 72px;

    flex-shrink: 0;

    border-radius: 4px;

    background: #06B6D4;

    margin-right: 15px;

    box-shadow:
        0 0 20px
        rgba(6,182,212,.35);
}

.title {

    margin: 0;

    font-size: 30px;

    line-height: 1.1;

    font-weight: 800;

    letter-spacing: .5px;

    animation:
        titleFade
        .8s
        ease-out;
}

.subtitle {

    margin-top: 5px;

    color: #8FA1B8;

    font-size: 13px;
}

.status {

    color: #22C55E;

    font-weight: 700;

    font-size: 12px;

    white-space: nowrap;
}


/* ======================================================
   スマホ用ナビ
   ====================================================== */

.mobile-nav {

    display: none;
}


/* ======================================================
   カード
   ====================================================== */

.card {

    background: #101C2C;

    border:
        1px solid
        #21334B;

    border-radius: 18px;

    padding: 25px;

    margin: 12px 0;

    box-shadow:
        0 15px 45px
        rgba(0,0,0,.12);

    animation:
        cardIn
        .5s
        ease-out;

    scroll-margin-top: 75px;
}

.card-title {

    font-size: 20px;

    line-height: 1.35;

    font-weight: 750;

    margin-bottom: 4px;
}

.card-subtitle {

    color: #8FA1B8;

    font-size: 12px;

    line-height: 1.6;

    margin-bottom: 18px;
}


/* ======================================================
   検索
   ====================================================== */

.search-row {

    display: flex;

    gap: 10px;

    align-items: center;

    margin-bottom: 15px;
}

input,
select {

    height: 44px;

    background: #142236;

    color: #F8FAFC;

    border:
        1px solid
        #21334B;

    border-radius: 9px;

    padding:
        0 13px;

    outline: none;

    min-width: 0;
}

input {

    width: 420px;
}

input:focus,
select:focus {

    border-color: #3B82F6;

    box-shadow:
        0 0 0 3px
        rgba(59,130,246,.12);
}

button {

    min-height: 44px;

    border: none;

    border-radius: 9px;

    padding:
        0 20px;

    color: white;

    background: #3B82F6;

    font-weight: 700;

    transition:
        background .2s,
        transform .1s,
        opacity .2s;
}

button:hover {

    background: #2563EB;

    transform:
        translateY(-1px);
}

button:active {

    transform:
        scale(.97);
}

button.secondary {

    background: #1A2A41;

    border:
        1px solid
        #21334B;
}

button.secondary:hover {

    background: #2563EB;
}

button.purple {

    background: #8B5CF6;
}

button.purple:hover {

    background: #7C3AED;
}

button:disabled {

    opacity: .55;

    cursor: wait;

    transform: none;
}


/* ======================================================
   テーブル
   ====================================================== */

.table-wrapper {

    width: 100%;

    overflow-x: auto;

    overflow-y: hidden;

    border-radius: 10px;

    -webkit-overflow-scrolling: touch;

    scrollbar-width: thin;
}

table {

    width: 100%;

    border-collapse: collapse;

    min-width: 650px;
}

th {

    text-align: left;

    background: #1A2A41;

    color: #CBD5E1;

    padding: 12px;

    font-size: 11px;

    white-space: nowrap;
}

td {

    padding: 12px;

    border-bottom:
        1px solid
        #21334B;

    color: #F8FAFC;

    font-size: 13px;

    white-space: nowrap;
}

tr {

    transition:
        background .15s;
}

tr:hover td {

    background: #142237;
}

tr.selected td {

    background: #245A98;
}


/* ======================================================
   コントロール
   ====================================================== */

.controls {

    display: flex;

    flex-wrap: wrap;

    gap: 10px;

    align-items: center;

    background: #0B1524;

    padding: 14px;

    border-radius: 12px;

    margin: 15px 0;
}

.controls label {

    color: #CBD5E1;

    font-size: 11px;

    font-weight: 700;

    white-space: nowrap;
}


/* ======================================================
   選手情報
   ====================================================== */

.info-grid {

    display: grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap: 10px;
}

.info-item {

    background: #142236;

    border:
        1px solid
        #21334B;

    border-radius: 10px;

    padding: 15px;

    min-width: 0;
}

.info-label {

    color: #8FA1B8;

    font-size: 11px;

    margin-bottom: 5px;
}

.info-value {

    color: #F8FAFC;

    font-weight: 700;

    font-size: 14px;

    overflow-wrap: anywhere;

    word-break: break-word;
}


/* ======================================================
   JO
   ====================================================== */

.jo-description {

    background: #0B1524;

    border-radius: 10px;

    padding: 14px;

    color: #CBD5E1;

    font-size: 12px;

    line-height: 1.8;

    margin-bottom: 15px;
}

.success {

    color: #22C55E !important;

    font-weight: 700;
}

.near {

    color: #F59E0B !important;

    font-weight: 700;
}


/* ======================================================
   グラフ
   ====================================================== */

.graph-wrapper {

    width: 100%;

    overflow: hidden;

    background: #0B1524;

    border-radius: 12px;

    padding: 10px;

    position: relative;
}

.graph-scroll {

    width: 100%;

    overflow: hidden;
}

#graph {

    display: block;

    width: 100%;

    height: 520px;

    min-height: 0;

    overflow: visible;

    touch-action: pan-y;
}

.graph-grid {

    stroke: #22334A;

    stroke-width: 1;
}

.graph-axis {

    stroke: #8FA1B8;

    stroke-width: 1.2;
}

.graph-line {

    fill: none;

    stroke: #3B82F6;

    stroke-width: 3;

    stroke-linecap: round;

    stroke-linejoin: round;
}

.graph-point {

    fill: #06B6D4;

    stroke: #F8FAFC;

    stroke-width: 2;

    cursor: pointer;

    transition:
        r .15s,
        fill .15s;
}

.graph-point:hover {

    fill: #22C55E;

    r: 8;
}

.graph-title {

    fill: #F8FAFC;

    font-size: 17px;

    font-weight: 700;
}

.graph-label {

    fill: #CBD5E1;

    font-size: 11px;
}

.graph-time {

    fill: #F8FAFC;

    font-size: 11px;

    font-weight: 700;

    pointer-events: none;
}

.graph-empty {

    fill: #8FA1B8;

    font-size: 16px;
}


/* ======================================================
   グラフ詳細表示
   ====================================================== */

.graph-tooltip {

    position: absolute;

    z-index: 20;

    display: none;

    max-width: min(
        340px,
        calc(100% - 20px)
    );

    background: #142236;

    border:
        1px solid
        #3B82F6;

    border-radius: 10px;

    padding: 10px 12px;

    color: #F8FAFC;

    font-size: 12px;

    line-height: 1.6;

    box-shadow:
        0 10px 30px
        rgba(0,0,0,.35);

    pointer-events: none;

    word-break: break-word;
}


/* ======================================================
   ローディング
   ====================================================== */

.loading {

    display: inline-flex;

    align-items: center;

    justify-content: center;

    gap: 8px;
}

.spinner {

    width: 14px;
    height: 14px;

    border:
        2px solid
        rgba(255,255,255,.2);

    border-top-color:
        #06B6D4;

    border-radius: 50%;

    animation:
        spin
        .7s
        linear infinite;
}


/* ======================================================
   トースト
   ====================================================== */

.toast {

    position: fixed;

    left: 50%;

    right: auto;

    bottom:
        calc(
            20px
            + env(safe-area-inset-bottom)
        );

    transform:
        translate(-50%, 20px);

    width:
        min(
            calc(100vw - 30px),
            500px
        );

    background: #142236;

    border:
        1px solid
        #21334B;

    color: #F8FAFC;

    padding: 14px 18px;

    border-radius: 10px;

    box-shadow:
        0 15px 40px
        rgba(0,0,0,.35);

    opacity: 0;

    pointer-events: none;

    transition: .25s;

    z-index: 1000;

    text-align: center;

    font-size: 14px;
}

.toast.show {

    opacity: 1;

    transform:
        translate(-50%, 0);
}


/* ======================================================
   アニメーション
   ====================================================== */

@keyframes spin {

    to {
        transform:
            rotate(360deg);
    }
}

@keyframes titleFade {

    from {

        opacity: 0;

        transform:
            translateY(-10px);
    }

    to {

        opacity: 1;

        transform:
            translateY(0);
    }
}

@keyframes cardIn {

    from {

        opacity: 0;

        transform:
            translateY(10px);
    }

    to {

        opacity: 1;

        transform:
            translateY(0);
    }
}


/* ======================================================
   タブレット
   ====================================================== */

@media (max-width: 900px) {

    .app {

        padding:
            18px
            14px
            70px;
    }

    .header {

        margin-bottom: 12px;
    }

    .title {

        font-size: 24px;
    }

    .header-accent {

        height: 58px;

        margin-right: 12px;
    }

    .card {

        padding: 18px;

        border-radius: 14px;
    }

    .search-row {

        flex-direction: column;

        align-items: stretch;
    }

    .search-row input {

        width: 100%;
    }

    .search-row button {

        width: 100%;
    }

    .info-grid {

        grid-template-columns:
            repeat(2, 1fr);
    }

    .controls {

        align-items: stretch;
    }

    .controls label {

        width: 100%;

        padding-top: 4px;
    }

    .controls select,
    .controls input,
    .controls button {

        width: 100%;
    }

    .graph-wrapper {

        padding: 5px;
    }

    #graph {

        width: 100%;

        height: 480px;

        min-height: 0;
    }
}


/* ======================================================
   スマートフォン
   ====================================================== */

@media (max-width: 600px) {

    body {

        overflow-x: hidden;
    }

    .app {

        padding:
            max(12px, env(safe-area-inset-top))
            10px
            calc(
                76px
                + env(safe-area-inset-bottom)
            );
    }

    .header {

        position: sticky;

        top: 0;

        z-index: 100;

        margin:
            0 -10px
            10px;

        padding:
            10px 12px;

        background:
            rgba(
                7,
                16,
                29,
                .94
            );

        backdrop-filter:
            blur(12px);

        -webkit-backdrop-filter:
            blur(12px);

        border-bottom:
            1px solid
            rgba(
                33,
                51,
                75,
                .8
            );
    }

    .header-accent {

        width: 4px;

        height: 45px;

        margin-right: 9px;
    }

    .title {

        font-size: 20px;

        letter-spacing: .2px;
    }

    .subtitle {

        font-size: 10px;

        margin-top: 2px;
    }

    .header-status {

        display: none;
    }


    /* ==================================================
       下部ナビ
       ================================================== */

    .mobile-nav {

        position: fixed;

        left: 0;
        right: 0;
        bottom: 0;

        z-index: 900;

        display: grid;

        grid-template-columns:
            repeat(4, 1fr);

        gap: 4px;

        padding:
            7px
            7px
            calc(
                7px
                + env(safe-area-inset-bottom)
            );

        background:
            rgba(
                11,
                21,
                36,
                .96
            );

        backdrop-filter:
            blur(14px);

        -webkit-backdrop-filter:
            blur(14px);

        border-top:
            1px solid
            #21334B;
    }

    .mobile-nav button {

        min-height: 52px;

        padding: 5px 2px;

        border-radius: 10px;

        background:
            transparent;

        color: #8FA1B8;

        border: none;

        font-size: 10px;

        font-weight: 700;

        line-height: 1.2;
    }

    .mobile-nav button span {

        display: block;

        font-size: 19px;

        line-height: 21px;

        margin-bottom: 2px;
    }

    .mobile-nav button:active {

        background: #142236;

        transform: scale(.96);
    }


    /* ==================================================
       カード
       ================================================== */

    .card {

        margin: 9px 0;

        padding: 15px;

        border-radius: 13px;

        scroll-margin-top: 75px;
    }

    .card-title {

        font-size: 18px;
    }

    .card-subtitle {

        font-size: 11px;

        margin-bottom: 14px;
    }


    /* ==================================================
       入力
       ================================================== */

    input,
    select,
    button {

        min-height: 48px;

        height: 48px;

        font-size: 16px;
    }

    button {

        padding:
            0 16px;
    }


    /* ==================================================
       検索結果
       ================================================== */

    .search-card-table {

        width: 100%;

        overflow: visible;
    }

    .search-card-table table {

        display: block;

        width: 100%;

        min-width: 0;

        table-layout: auto;
    }

    #searchResults {

        display: block;

        width: 100%;

        min-width: 0;
    }

    #searchResults tr {

        display: block;

        width: 100%;

        min-width: 0;

        position: relative;

        margin-bottom: 9px;

        padding: 11px;

        background: #142236;

        border:
            1px solid
            #21334B;

        border-radius: 11px;

        cursor: pointer;

        overflow: hidden;
    }

    #searchResults tr:hover td,
    #searchResults tr.selected td {

        background: transparent;
    }

    #searchResults tr.selected {

        border-color: #3B82F6;

        background: #17365A;

        box-shadow:
            0 0 0 1px
            rgba(59,130,246,.2);
    }

    #searchResults td {

        display: block;

        width: 100%;

        max-width: 100%;

        border: none;

        padding: 3px 5px;

        white-space: normal;

        overflow-wrap: anywhere;

        word-break: break-word;

        font-size: 13px;

        line-height: 1.5;

    }

    #searchResults td:first-child {

        font-size: 15px;

        font-weight: 800;

        color: #F8FAFC;

        padding-bottom: 6px;
    }

    #searchResults td:nth-child(2) {

        color: #CBD5E1;

        font-size: 12px;

        line-height: 1.5;
    }

    #searchResults td:nth-child(3),
    #searchResults td:nth-child(4) {

        display: inline-block;

        width: auto;

        max-width: 100%;

        color: #8FA1B8;

        font-size: 11px;

        margin-right: 10px;

        vertical-align: top;
    }

    #searchResults thead {

        display: none;
    }


    /* ==================================================
       選手情報
       ================================================== */

    .info-grid {

        grid-template-columns:
            repeat(2, 1fr);

        gap: 7px;
    }

    .info-item {

        padding: 11px;

        border-radius: 9px;

        min-width: 0;
    }

    .info-label {

        font-size: 10px;
    }

    .info-value {

        font-size: 13px;

        overflow-wrap: anywhere;

        word-break: break-word;
    }


    /* ==================================================
       コントロール
       ================================================== */

    .controls {

        display: grid;

        grid-template-columns:
            1fr;

        gap: 7px;

        padding: 11px;

        border-radius: 10px;
    }

    .controls label {

        width: auto;

        padding: 2px 0 0;
    }

    .controls select,
    .controls input,
    .controls button {

        width: 100% !important;
    }


    /* ==================================================
       一般テーブル
       ================================================== */

    .table-wrapper {

        margin-left: -2px;

        width:
            calc(100% + 4px);

        overflow-x: auto;
    }

    .table-wrapper table {

        min-width: 620px;
    }

    th {

        padding: 10px;

        font-size: 10px;
    }

    td {

        padding: 10px;

        font-size: 12px;
    }


    /* ==================================================
       ベスト・JOは横スクロール
       ================================================== */

    #bestResults,
    #joResults {

        -webkit-overflow-scrolling:
            touch;
    }


    /* ==================================================
       JO
       ================================================== */

    .jo-description {

        font-size: 11px;

        padding: 11px;

        line-height: 1.7;
    }


    /* ==================================================
       グラフ
       ================================================== */

    .graph-wrapper {

        width: 100%;

        padding: 3px;

        border-radius: 9px;

        overflow: hidden;
    }

    .graph-scroll {

        width: 100%;

        overflow: hidden;
    }

    #graph {

        display: block;

        width: 100%;

        height: 430px;

        min-height: 0;

        max-width: 100%;
    }

    .graph-title {

        font-size: 17px;
    }

    .graph-label {

        font-size: 11px;
    }

    .graph-time {

        font-size: 10px;
    }

    .graph-line {

        stroke-width: 3;
    }

    .graph-point {

        stroke-width: 2;

        cursor: pointer;
    }

    .graph-tooltip {

        font-size: 11px;

        padding: 9px 10px;
    }
}


/* ======================================================
   小型スマートフォン
   ====================================================== */

@media (max-width: 380px) {

    .app {

        padding-left: 7px;

        padding-right: 7px;
    }

    .header {

        margin-left: -7px;

        margin-right: -7px;
    }

    .card {

        padding: 12px;
    }

    .title {

        font-size: 18px;
    }

    .info-grid {

        gap: 5px;
    }

    .info-item {

        padding: 9px;
    }

    .mobile-nav button {

        font-size: 9px;
    }

    .mobile-nav button span {

        font-size: 17px;
    }

    #graph {

        height: 390px;
    }
}


/* ======================================================
   モーション軽減
   ====================================================== */

@media (prefers-reduced-motion: reduce) {

    html {

        scroll-behavior: auto;
    }

    *,
    *::before,
    *::after {

        animation-duration: .01ms !important;

        animation-iteration-count: 1 !important;

        transition-duration: .01ms !important;
    }
}

</style>

</head>


<body>


<div class="app">


    <!-- ================================================= -->
    <!-- HEADER -->
    <!-- ================================================= -->

    <header class="header">

        <div class="header-left">

            <div class="header-accent"></div>

            <div>

                <h1 class="title">
                    SWIM MANAGER
                </h1>

                <div class="subtitle">
                    競泳選手記録マネージャー
                </div>

            </div>

        </div>

        <div
            id="headerStatus"
            class="status header-status"
        >
            ● READY
        </div>

    </header>


    <!-- ================================================= -->
    <!-- 検索 -->
    <!-- ================================================= -->

    <section
        class="card"
        id="searchSection"
    >

        <div class="card-title">
            選手を検索
        </div>

        <div class="card-subtitle">
            氏名から Swim Result の選手情報を検索します
        </div>

        <div class="search-row">

            <input
                id="searchInput"
                type="text"
                placeholder="選手名を入力"
                autocomplete="off"
                enterkeyhint="search"
            >

            <button
                id="searchButton"
                onclick="searchAthletes()"
            >
                検索
            </button>

            <span
                id="searchStatus"
                class="status-text"
            ></span>

        </div>

        <div class="table-wrapper search-card-table">

            <table>

                <thead>

                    <tr>

                        <th>氏名</th>
                        <th>所属</th>
                        <th>性別</th>
                        <th>選手コード</th>

                    </tr>

                </thead>

                <tbody
                    id="searchResults"
                ></tbody>

            </table>

        </div>

        <div style="margin-top:15px;">

            <button
                class="secondary"
                style="width:100%;"
                onclick="selectAthlete()"
            >
                この選手を選択
            </button>

        </div>

    </section>


    <!-- ================================================= -->
    <!-- 選手情報 -->
    <!-- ================================================= -->

    <section
        class="card"
        id="athleteSection"
    >

        <div class="card-title">
            選手情報
        </div>

        <div
            class="card-subtitle"
            id="athleteLoading"
        >
            選手未選択
        </div>

        <div
            class="info-grid"
            id="athleteInfo"
        >

            <div class="info-item">

                <div class="info-label">
                    氏名
                </div>

                <div
                    class="info-value"
                    id="athleteName"
                >
                    -
                </div>

            </div>

            <div class="info-item">

                <div class="info-label">
                    所属
                </div>

                <div
                    class="info-value"
                    id="athleteSchool"
                >
                    -
                </div>

            </div>

            <div class="info-item">

                <div class="info-label">
                    性別
                </div>

                <div
                    class="info-value"
                    id="athleteGender"
                >
                    -
                </div>

            </div>

            <div class="info-item">

                <div class="info-label">
                    選手コード
                </div>

                <div
                    class="info-value"
                    id="athleteCode"
                >
                    -
                </div>

            </div>

        </div>

        <div
            style="
                margin-top:15px;
                color:#8FA1B8;
                font-size:12px;
            "
            id="recordStatus"
        ></div>

    </section>


    <!-- ================================================= -->
    <!-- ベスト記録 -->
    <!-- ================================================= -->

    <section
        class="card"
        id="bestSection"
    >

        <div class="card-title">
            ベスト記録
        </div>

        <div class="card-subtitle">
            期間・種目・水路・距離を指定して自己ベストを表示
        </div>

        <div class="controls">

            <label>種目</label>

            <select id="bestStyle">

                <option value="すべて">
                    すべて
                </option>

                <option>自由形</option>
                <option>背泳ぎ</option>
                <option>平泳ぎ</option>
                <option>バタフライ</option>
                <option>個人メドレー</option>

            </select>


            <label>水路</label>

            <select id="bestWaterway">

                <option value="すべて">
                    すべて
                </option>

                <option>長水路</option>
                <option>短水路</option>

            </select>


            <label>距離</label>

            <select id="bestDistance">

                <option value="すべて">
                    すべて
                </option>

                <option>50m</option>
                <option>100m</option>
                <option>200m</option>
                <option>400m</option>
                <option>800m</option>
                <option>1500m</option>

            </select>


            <label>期間</label>

            <select id="bestPeriod">

                <option>
                    直近6ヶ月
                </option>

                <option>
                    2026年度
                </option>

                <option>
                    2025年度以降
                </option>

                <option selected>
                    2024年度以降
                </option>

                <option>
                    すべて
                </option>

            </select>


            <button
                onclick="updateBestTable()"
            >
                表示更新
            </button>

        </div>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>種目</th>
                        <th>水路</th>
                        <th>距離</th>
                        <th>日付</th>
                        <th>タイム</th>
                        <th>大会</th>

                    </tr>

                </thead>

                <tbody
                    id="bestResults"
                ></tbody>

            </table>

        </div>

    </section>


    <!-- ================================================= -->
    <!-- JO -->
    <!-- ================================================= -->

    <section
        class="card"
        id="joSection"
    >

        <div
            style="
                display:flex;
                justify-content:space-between;
                align-items:center;
                gap:10px;
            "
        >

            <div class="card-title">
                全国JOCジュニアオリンピックカップ
            </div>

            <div
                style="
                    color:#06B6D4;
                    font-size:11px;
                    font-weight:700;
                    white-space:nowrap;
                "
            >
                JO STANDARD
            </div>

        </div>

        <div class="card-subtitle">
            自己ベストと公式JO標準記録を比較
        </div>


        <div class="controls">

            <label>年齢</label>

            <input
                id="joAge"
                type="number"
                value="14"
                min="1"
                max="30"
                style="width:80px;"
            >


            <label>性別</label>

            <select id="joGender">

                <option>男子</option>
                <option>女子</option>

            </select>


            <label>種目</label>

            <select id="joStyle">

                <option>すべて</option>
                <option>自由形</option>
                <option>背泳ぎ</option>
                <option>平泳ぎ</option>
                <option>バタフライ</option>
                <option>個人メドレー</option>

            </select>


            <label>水路</label>

            <select id="joWaterway">

                <option>すべて</option>
                <option>長水路</option>
                <option>短水路</option>

            </select>


            <label>距離</label>

            <select id="joDistance">

                <option>すべて</option>
                <option>50m</option>
                <option>100m</option>
                <option>200m</option>
                <option>400m</option>
                <option>800m</option>
                <option>1500m</option>

            </select>


            <button
                class="purple"
                onclick="fetchJO()"
            >
                公式サイトから取得
            </button>


            <button
                onclick="updateJO()"
            >
                比較を更新
            </button>

        </div>


        <div
            id="joStatus"
            class="status-text"
        >
            JO標準記録：未取得
        </div>


        <div class="jo-description">

            達成率 =
            JO標準記録 ÷ 自己ベスト × 100

            <br>

            100%以上：
            JO標準記録を突破

            &nbsp;&nbsp;&nbsp;

            100%未満：
            JO標準記録までの差を表示

        </div>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        <th>種目</th>
                        <th>水路</th>
                        <th>距離</th>
                        <th>自己ベスト</th>
                        <th>JO標準</th>
                        <th>あと</th>
                        <th>達成率</th>
                        <th>判定</th>

                    </tr>

                </thead>

                <tbody
                    id="joResults"
                ></tbody>

            </table>

        </div>

    </section>


    <!-- ================================================= -->
    <!-- グラフ -->
    <!-- ================================================= -->

    <section
        class="card"
        id="graphSection"
    >

        <div class="card-title">
            タイム推移
        </div>

        <div class="card-subtitle">
            大会ごとの記録を時系列で確認
        </div>


        <div class="controls">

            <label>種目</label>

            <select id="graphStyle">

                <option>自由形</option>
                <option>背泳ぎ</option>
                <option>平泳ぎ</option>
                <option>バタフライ</option>
                <option>個人メドレー</option>

            </select>


            <label>距離</label>

            <select id="graphDistance">

                <option>50m</option>
                <option>100m</option>
                <option>200m</option>
                <option>400m</option>
                <option>800m</option>
                <option>1500m</option>

            </select>


            <label>水路</label>

            <select id="graphWaterway">

                <option>長水路</option>
                <option>短水路</option>

            </select>


            <button
                onclick="updateGraph()"
            >
                グラフ更新
            </button>

        </div>


        <div class="graph-wrapper">

            <div class="graph-scroll">

                <svg
                    id="graph"
                    viewBox="0 0 1200 600"
                    preserveAspectRatio="xMidYMid meet"
                    role="img"
                    aria-label="競泳タイム推移グラフ"
                ></svg>

            </div>

            <div
                id="graphTooltip"
                class="graph-tooltip"
            ></div>

        </div>

    </section>


</div>


<!-- =====================================================
     スマホ用下部ナビ
     ===================================================== -->

<nav
    class="mobile-nav"
    aria-label="ページ内ナビゲーション"
>

    <button
        onclick="scrollToSection('searchSection')"
    >
        <span>🔎</span>
        選手
    </button>

    <button
        onclick="scrollToSection('bestSection')"
    >
        <span>🏊</span>
        ベスト
    </button>

    <button
        onclick="scrollToSection('joSection')"
    >
        <span>🏆</span>
        JO
    </button>

    <button
        onclick="scrollToSection('graphSection')"
    >
        <span>📈</span>
        グラフ
    </button>

</nav>


<div
    id="toast"
    class="toast"
></div>


<script>

let selectedAthlete = null;

let selectedAthleteId = null;

let allRecords = [];

let joStandardsLoaded = false;


// ======================================================
// セクション移動
// ======================================================

function scrollToSection(
    id
) {

    const element =
        document.getElementById(
            id
        );

    if (!element) {
        return;
    }

    element.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}


// ======================================================
// 通知
// ======================================================

function toast(message) {

    const element =
        document.getElementById(
            "toast"
        );

    element.textContent = message;

    element.classList.add(
        "show"
    );

    clearTimeout(
        window.toastTimer
    );

    window.toastTimer =
        setTimeout(() => {

            element.classList.remove(
                "show"
            );

        }, 2500);
}


// ======================================================
// ステータス
// ======================================================

function setStatus(
    text,
    color = "#22C55E"
) {

    const element =
        document.getElementById(
            "headerStatus"
        );

    element.textContent = text;

    element.style.color =
        color;
}


// ======================================================
// 選手検索
// ======================================================

async function searchAthletes() {

    const input =
        document.getElementById(
            "searchInput"
        );

    const button =
        document.getElementById(
            "searchButton"
        );

    const status =
        document.getElementById(
            "searchStatus"
        );

    const name =
        input.value.trim();

    if (!name) {

        toast(
            "選手名を入力してください。"
        );

        input.focus();

        return;
    }

    button.disabled = true;

    button.innerHTML =
        '<span class="loading">' +
        '<span class="spinner"></span>' +
        '検索中...' +
        '</span>';

    status.textContent =
        "選手を検索しています";

    setStatus(
        "● SEARCHING",
        "#F59E0B"
    );

    try {

        const response =
            await fetch(
                "/api/search?name=" +
                encodeURIComponent(name)
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error ||
                "検索に失敗しました。"
            );
        }

        const tbody =
            document.getElementById(
                "searchResults"
            );

        tbody.innerHTML = "";

        data.results.forEach(
            (athlete, index) => {

                const tr =
                    document.createElement(
                        "tr"
                    );

                tr.dataset.index =
                    index;

                tr.innerHTML = `
                    <td>${escapeHtml(
                        athlete.name
                    )}</td>

                    <td>${escapeHtml(
                        athlete.school
                    )}</td>

                    <td>${escapeHtml(
                        athlete.gender
                    )}</td>

                    <td>${escapeHtml(
                        athlete.swimmer_code
                    )}</td>
                `;

                tr.addEventListener(
                    "click",
                    () => {

                        document
                            .querySelectorAll(
                                "#searchResults tr"
                            )
                            .forEach(
                                row =>
                                    row.classList.remove(
                                        "selected"
                                    )
                            );

                        tr.classList.add(
                            "selected"
                        );

                        selectedAthlete =
                            athlete;

                        toast(
                            athlete.name +
                            " を選択しました"
                        );
                    }
                );

                tr.addEventListener(
                    "dblclick",
                    () => {

                        selectedAthlete =
                            athlete;

                        selectAthlete();
                    }
                );

                tbody.appendChild(
                    tr
                );
            }
        );

        status.textContent =
            data.results.length +
            "件";

        setStatus(
            "● READY",
            "#22C55E"
        );

        if (
            data.results.length === 1
        ) {

            const row =
                tbody.querySelector(
                    "tr"
                );

            if (row) {

                row.classList.add(
                    "selected"
                );

                selectedAthlete =
                    data.results[0];

                setTimeout(
                    selectAthlete,
                    200
                );
            }
        }

        if (
            data.results.length > 1
        ) {

            toast(
                data.results.length +
                "件見つかりました。選手をタップしてください。"
            );
        }

    } catch (error) {

        status.textContent =
            "検索に失敗しました";

        setStatus(
            "● ERROR",
            "#EF4444"
        );

        toast(
            error.message
        );

    } finally {

        button.disabled = false;

        button.textContent =
            "検索";
    }
}


// ======================================================
// 選手選択
// ======================================================

async function selectAthlete() {

    if (!selectedAthlete) {

        toast(
            "選手を選択してください。"
        );

        return;
    }

    const code =
        selectedAthlete.swimmer_code;

    if (!code) {

        toast(
            "選手コードを取得できませんでした。"
        );

        return;
    }

    selectedAthleteId =
        3 * (
            Number(code)
            + 10000000
        ) + 3;

    setStatus(
        "● LOADING",
        "#F59E0B"
    );

    document.getElementById(
        "athleteLoading"
    ).textContent =
        "選手情報を取得しています...";

    try {

        const response =
            await fetch(
                "/api/athlete/" +
                selectedAthleteId
            );

        const athlete =
            await response.json();

        if (!response.ok) {

            throw new Error(
                athlete.error
            );
        }

        document.getElementById(
            "athleteName"
        ).textContent =
            athlete.name || "-";

        document.getElementById(
            "athleteSchool"
        ).textContent =
            athlete.school || "-";

        document.getElementById(
            "athleteGender"
        ).textContent =
            athlete.gender || "-";

        document.getElementById(
            "athleteCode"
        ).textContent =
            athlete.swimmer_code || code;

        document.getElementById(
            "athleteLoading"
        ).textContent =
            "選手情報取得済み";

        if (athlete.age) {

            document.getElementById(
                "joAge"
            ).value =
                athlete.age;
        }

        if (athlete.gender) {

            document.getElementById(
                "joGender"
            ).value =
                athlete.gender;
        }

        await loadRecords();

        scrollToSection(
            "athleteSection"
        );

    } catch (error) {

        setStatus(
            "● ERROR",
            "#EF4444"
        );

        toast(
            error.message
        );
    }
}


// ======================================================
// 全記録
// ======================================================

async function loadRecords() {

    const status =
        document.getElementById(
            "recordStatus"
        );

    status.innerHTML =
        '<span class="loading">' +
        '<span class="spinner"></span>' +
        '全種目の記録を取得しています...' +
        '</span>';

    try {

        const response =
            await fetch(
                "/api/records/" +
                selectedAthleteId
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
            );
        }

        allRecords =
            data.records || [];

        status.textContent =
            "記録数: " +
            allRecords.length +
            "件";

        setStatus(
            "● LOADED",
            "#22C55E"
        );

        updateBestTable();

        await fetchJO();

        updateGraph();

    } catch (error) {

        status.textContent =
            "記録取得に失敗しました";

        setStatus(
            "● ERROR",
            "#EF4444"
        );

        toast(
            error.message
        );
    }
}


// ======================================================
// ベスト記録
// ======================================================

function updateBestTable() {

    const tbody =
        document.getElementById(
            "bestResults"
        );

    tbody.innerHTML = "";

    if (!allRecords.length) {
        return;
    }

    const style =
        document.getElementById(
            "bestStyle"
        ).value;

    const waterway =
        document.getElementById(
            "bestWaterway"
        ).value;

    const distance =
        document.getElementById(
            "bestDistance"
        ).value;

    const period =
        document.getElementById(
            "bestPeriod"
        ).value;

    let records =
        filterPeriod(
            allRecords,
            period
        );

    records =
        records.filter(
            record => {

                if (
                    style !== "すべて"
                    && record.style !== style
                ) {
                    return false;
                }

                if (
                    waterway !== "すべて"
                    && record.waterway !== waterway
                ) {
                    return false;
                }

                if (
                    distance !== "すべて"
                    && record.distance !== distance
                ) {
                    return false;
                }

                return true;
            }
        );

    const bests = {};

    records.forEach(
        record => {

            if (
                record.seconds === null
                ||
                !Number.isFinite(
                    Number(record.seconds)
                )
            ) {
                return;
            }

            const key =
                record.style_code +
                "_" +
                record.waterway_code +
                "_" +
                record.distance_code;

            if (
                !bests[key]
                || record.seconds <
                   bests[key].seconds
            ) {

                bests[key] =
                    record;
            }
        }
    );

    Object.values(bests)
        .sort(
            (a, b) =>
                a.seconds -
                b.seconds
        )
        .forEach(
            record => {

                const tr =
                    document.createElement(
                        "tr"
                    );

                tr.innerHTML = `
                    <td>${escapeHtml(
                        record.style
                    )}</td>

                    <td>${escapeHtml(
                        record.waterway
                    )}</td>

                    <td>${escapeHtml(
                        record.distance
                    )}</td>

                    <td>${escapeHtml(
                        record.date
                    )}</td>

                    <td>
                        <strong>
                            ${escapeHtml(
                                record.time
                            )}
                        </strong>
                    </td>

                    <td>${escapeHtml(
                        record.game
                    )}</td>
                `;

                tbody.appendChild(
                    tr
                );
            }
        );
}


// ======================================================
// 期間フィルター
// ======================================================

function filterPeriod(
    records,
    period
) {

    if (period === "すべて") {
        return records;
    }

    const now =
        new Date();

    let start;

    if (
        period ===
        "直近6ヶ月"
    ) {

        start =
            new Date(
                now.getTime()
                -
                183 *
                24 *
                60 *
                60 *
                1000
            );

    } else if (
        period ===
        "2026年度"
    ) {

        start =
            new Date(
                "2026-04-01"
            );

    } else if (
        period ===
        "2025年度以降"
    ) {

        start =
            new Date(
                "2025-04-01"
            );

    } else {

        start =
            new Date(
                "2024-04-01"
            );
    }

    return records.filter(
        record => {

            if (!record.date) {
                return false;
            }

            const date =
                parseGraphDate(
                    record.date
                );

            if (!date) {
                return false;
            }

            return date >= start;
        }
    );
}


// ======================================================
// JO取得
// ======================================================

async function fetchJO() {

    const status =
        document.getElementById(
            "joStatus"
        );

    status.textContent =
        "公式サイトから取得中...";

    try {

        const response =
            await fetch(
                "/api/jo"
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
            );
        }

        joStandardsLoaded = true;

        status.textContent =
            "JO標準記録：取得済み (" +
            data.standards.length +
            "件)";

        status.style.color =
            "#22C55E";

        updateJO();

    } catch (error) {

        status.textContent =
            "JO標準記録：取得失敗";

        status.style.color =
            "#EF4444";

        toast(
            error.message
        );
    }
}


// ======================================================
// JO比較
// ======================================================

async function updateJO() {

    if (!selectedAthleteId) {
        return;
    }

    if (!joStandardsLoaded) {
        return;
    }

    const data = {

        athlete_id:
            selectedAthleteId,

        age:
            Number(
                document.getElementById(
                    "joAge"
                ).value
            ),

        gender:
            document.getElementById(
                "joGender"
            ).value,

        period:
            document.getElementById(
                "bestPeriod"
            ).value,

        style:
            document.getElementById(
                "joStyle"
            ).value,

        waterway:
            document.getElementById(
                "joWaterway"
            ).value,

        distance:
            document.getElementById(
                "joDistance"
            ).value
    };

    try {

        const response =
            await fetch(
                "/api/jo/compare",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify(
                            data
                        )
                }
            );

        const result =
            await response.json();

        if (!response.ok) {

            throw new Error(
                result.error
            );
        }

        const tbody =
            document.getElementById(
                "joResults"
            );

        tbody.innerHTML = "";

        result.results.forEach(
            item => {

                const tr =
                    document.createElement(
                        "tr"
                    );

                if (
                    item.status ===
                    "JO突破"
                ) {

                    tr.classList.add(
                        "success"
                    );

                } else if (
                    item.difference_seconds
                    <= 1
                ) {

                    tr.classList.add(
                        "near"
                    );
                }

                tr.innerHTML = `
                    <td>${escapeHtml(
                        item.style
                    )}</td>

                    <td>${escapeHtml(
                        item.waterway
                    )}</td>

                    <td>${escapeHtml(
                        item.distance
                    )}</td>

                    <td>${escapeHtml(
                        item.best
                    )}</td>

                    <td>${escapeHtml(
                        item.standard
                    )}</td>

                    <td>${escapeHtml(
                        item.difference
                    )}</td>

                    <td>${escapeHtml(
                        item.rate
                    )}</td>

                    <td>${escapeHtml(
                        item.status
                    )}</td>
                `;

                tbody.appendChild(
                    tr
                );
            }
        );

    } catch (error) {

        toast(
            error.message
        );
    }
}


// ======================================================
// SVGグラフ
// ======================================================

function updateGraph() {

    const svg =
        document.getElementById(
            "graph"
        );

    const tooltip =
        document.getElementById(
            "graphTooltip"
        );

    svg.innerHTML = "";

    if (tooltip) {

        tooltip.style.display =
            "none";

        tooltip.innerHTML = "";
    }

    if (!allRecords.length) {

        drawGraphMessage(
            svg,
            "記録がありません"
        );

        return;
    }

    const style =
        document.getElementById(
            "graphStyle"
        ).value;

    const distance =
        document.getElementById(
            "graphDistance"
        ).value;

    const waterway =
        document.getElementById(
            "graphWaterway"
        ).value;


    /*
     * 重要：
     * ここで種目・距離・水路をすべて一致させる。
     * そのため、別種目などの記録が
     * 同じ線に混ざることはない。
     */

    let points =
        allRecords
            .filter(
                record => {

                    if (
                        record.style !== style
                    ) {
                        return false;
                    }

                    if (
                        record.distance !== distance
                    ) {
                        return false;
                    }

                    if (
                        record.waterway !== waterway
                    ) {
                        return false;
                    }

                    if (!record.date) {
                        return false;
                    }

                    if (
                        record.seconds === null
                        ||
                        record.seconds === undefined
                    ) {
                        return false;
                    }

                    const seconds =
                        Number(
                            record.seconds
                        );

                    if (
                        !Number.isFinite(
                            seconds
                        )
                    ) {
                        return false;
                    }

                    if (seconds <= 0) {
                        return false;
                    }

                    return true;
                }
            )
            .map(
                (record, originalIndex) => {

                    const dateObject =
                        parseGraphDate(
                            record.date
                        );

                    return {
                        ...record,

                        originalIndex:
                            originalIndex,

                        dateObject:
                            dateObject,

                        seconds:
                            Number(
                                record.seconds
                            )
                    };
                }
            )
            .filter(
                record => {

                    return (
                        record.dateObject !== null
                        &&
                        !Number.isNaN(
                            record.dateObject.getTime()
                        )
                    );
                }
            );


    /*
     * 日付順に並べる。
     *
     * 同じ日なら、
     * タイムの速い順。
     *
     * originalIndexを最後の比較に使うことで
     * sortによる順序の不安定さを防ぐ。
     */

    points.sort(
        (a, b) => {

            const dateDifference =
                a.dateObject.getTime()
                -
                b.dateObject.getTime();

            if (
                dateDifference !== 0
            ) {

                return dateDifference;
            }

            const timeDifference =
                a.seconds -
                b.seconds;

            if (
                timeDifference !== 0
            ) {

                return timeDifference;
            }

            return (
                a.originalIndex -
                b.originalIndex
            );
        }
    );


    if (!points.length) {

        drawGraphMessage(
            svg,
            "この種目の記録がありません"
        );

        return;
    }


    /*
     * SVGキャンバス
     */

    const SVG_WIDTH = 1200;

    const SVG_HEIGHT = 600;

    const LEFT = 105;

    const RIGHT = 45;

    const TOP = 70;

    const BOTTOM = 105;


    const plotWidth =
        SVG_WIDTH
        -
        LEFT
        -
        RIGHT;

    const plotHeight =
        SVG_HEIGHT
        -
        TOP
        -
        BOTTOM;


    /*
     * タイム範囲
     */

    const times =
        points.map(
            point =>
                point.seconds
        );

    let minTime =
        Math.min(
            ...times
        );

    let maxTime =
        Math.max(
            ...times
        );


    if (
        minTime === maxTime
    ) {

        minTime -= 1;

        maxTime += 1;
    }


    const originalRange =
        maxTime - minTime;

    const padding =
        Math.max(
            originalRange * 0.10,
            0.25
        );

    minTime -= padding;

    maxTime += padding;


    /*
     * X座標
     */

    function xPosition(index) {

        if (points.length === 1) {

            return (
                LEFT
                +
                plotWidth / 2
            );
        }

        return (
            LEFT
            +
            plotWidth
            *
            index
            /
            (
                points.length - 1
            )
        );
    }


    /*
     * Y座標
     *
     * 速いタイムほど上。
     */

    function yPosition(seconds) {

        const ratio =
            (
                seconds
                -
                minTime
            )
            /
            (
                maxTime
                -
                minTime
            );

        return (
            TOP
            +
            ratio
            *
            plotHeight
        );
    }


    const coordinates =
        points.map(
            (point, index) => {

                return {
                    x:
                        xPosition(
                            index
                        ),

                    y:
                        yPosition(
                            point.seconds
                        ),

                    point
                };
            }
        );


    /*
     * タイトル
     */

    const title =
        createSvgElement(
            "text",
            {
                x:
                    SVG_WIDTH / 2,

                y: 30,

                class:
                    "graph-title",

                "text-anchor":
                    "middle"
            }
        );

    title.textContent =
        style
        + " "
        + distance
        + " "
        + waterway;

    svg.appendChild(
        title
    );


    /*
     * 件数
     */

    const countLabel =
        createSvgElement(
            "text",
            {
                x:
                    SVG_WIDTH - RIGHT,

                y: 30,

                class:
                    "graph-label",

                "text-anchor":
                    "end"
            }
        );

    countLabel.textContent =
        points.length
        +
        " records";

    svg.appendChild(
        countLabel
    );


    /*
     * グリッド
     */

    const gridCount = 6;

    for (
        let i = 0;
        i < gridCount;
        i++
    ) {

        const y =
            TOP
            +
            plotHeight
            *
            i
            /
            (
                gridCount - 1
            );


        const line =
            createSvgElement(
                "line",
                {
                    x1:
                        LEFT,

                    y1:
                        y,

                    x2:
                        SVG_WIDTH - RIGHT,

                    y2:
                        y,

                    class:
                        "graph-grid"
                }
            );

        svg.appendChild(
            line
        );


        const value =
            maxTime
            -
            (
                maxTime
                -
                minTime
            )
            *
            i
            /
            (
                gridCount - 1
            );


        const label =
            createSvgElement(
                "text",
                {
                    x:
                        LEFT - 15,

                    y:
                        y + 5,

                    class:
                        "graph-label",

                    "text-anchor":
                        "end"
                }
            );

        label.textContent =
            formatSeconds(
                value
            );

        svg.appendChild(
            label
        );
    }


    /*
     * Y軸
     */

    const yAxis =
        createSvgElement(
            "line",
            {
                x1:
                    LEFT,

                y1:
                    TOP,

                x2:
                    LEFT,

                y2:
                    SVG_HEIGHT - BOTTOM,

                class:
                    "graph-axis"
            }
        );

    svg.appendChild(
        yAxis
    );


    /*
     * X軸
     */

    const xAxis =
        createSvgElement(
            "line",
            {
                x1:
                    LEFT,

                y1:
                    SVG_HEIGHT - BOTTOM,

                x2:
                    SVG_WIDTH - RIGHT,

                y2:
                    SVG_HEIGHT - BOTTOM,

                class:
                    "graph-axis"
            }
        );

    svg.appendChild(
        xAxis
    );


    /*
     * 線グラフ
     *
     * pointsはすでに
     * 同じ種目・距離・水路だけに絞られている。
     */

    if (
        coordinates.length >= 2
    ) {

        const pathParts = [];

        coordinates.forEach(
            (item, index) => {

                const command =
                    index === 0
                    ? "M "
                    : "L ";

                pathParts.push(
                    command
                    +
                    item.x.toFixed(2)
                    +
                    " "
                    +
                    item.y.toFixed(2)
                );
            }
        );


        const path =
            createSvgElement(
                "path",
                {
                    d:
                        pathParts.join(
                            " "
                        ),

                    class:
                        "graph-line"
                }
            );

        svg.appendChild(
            path
        );
    }


    /*
     * X軸の日付ラベル
     */

    const labelIndexes =
        calculateLabelIndexes(
            points.length
        );

    labelIndexes.forEach(
        index => {

            const item =
                coordinates[index];

            if (!item) {
                return;
            }

            const date =
                item.point.dateObject;


            const label =
                createSvgElement(
                    "text",
                    {
                        x:
                            item.x,

                        y:
                            SVG_HEIGHT
                            -
                            BOTTOM
                            +
                            32,

                        class:
                            "graph-label",

                        "text-anchor":
                            "middle"
                    }
                );


            label.textContent =
                (
                    date.getMonth()
                    + 1
                )
                .toString()
                .padStart(
                    2,
                    "0"
                )
                +
                "/"
                +
                date.getDate()
                    .toString()
                    .padStart(
                        2,
                        "0"
                    );


            svg.appendChild(
                label
            );
        }
    );


    /*
     * 点
     */

    coordinates.forEach(
        item => {

            const circle =
                createSvgElement(
                    "circle",
                    {
                        cx:
                            item.x,

                        cy:
                            item.y,

                        r:
                            7,

                        class:
                            "graph-point"
                    }
                );


            /*
             * SVG標準のtitle。
             *
             * PCではマウスを乗せると
             * ブラウザ標準のツールチップも出る。
             */

            const svgTitle =
                createSvgElement(
                    "title"
                );

            svgTitle.textContent =
                buildPointTooltip(
                    item.point
                );

            circle.appendChild(
                svgTitle
            );


            /*
             * マウス操作
             */

            circle.addEventListener(
                "mouseenter",
                event => {

                    showGraphTooltip(
                        event,
                        item.point
                    );
                }
            );


            circle.addEventListener(
                "mouseleave",
                () => {

                    hideGraphTooltip();
                }
            );


            /*
             * スマホ操作
             */

            circle.addEventListener(
                "click",
                event => {

                    showGraphTooltip(
                        event,
                        item.point
                    );

                    toast(
                        buildPointTooltip(
                            item.point
                        )
                    );
                }
            );


            svg.appendChild(
                circle
            );


            /*
             * タイム表示
             */

            const timeLabel =
                createSvgElement(
                    "text",
                    {
                        x:
                            item.x,

                        y:
                            item.y - 16,

                        class:
                            "graph-time",

                        "text-anchor":
                            "middle"
                    }
                );


            timeLabel.textContent =
                formatSeconds(
                    item.point.seconds
                );


            svg.appendChild(
                timeLabel
            );
        }
    );
}


// ======================================================
// SVG要素生成
// ======================================================

function createSvgElement(
    tag,
    attributes = {}
) {

    const element =
        document.createElementNS(
            "http://www.w3.org/2000/svg",
            tag
        );

    Object.entries(
        attributes
    ).forEach(
        ([key, value]) => {

            element.setAttribute(
                key,
                value
            );
        }
    );

    return element;
}


// ======================================================
// グラフ用日付
// ======================================================

function parseGraphDate(
    value
) {

    if (!value) {
        return null;
    }

    const text =
        String(value).trim();


    /*
     * YYYY-MM-DD
     */

    const match =
        text.match(
            /^(\d{4})-(\d{2})-(\d{2})/
        );

    if (match) {

        const date =
            new Date(
                Number(match[1]),
                Number(match[2]) - 1,
                Number(match[3])
            );

        if (
            !Number.isNaN(
                date.getTime()
            )
        ) {

            return date;
        }
    }


    /*
     * YYYY/MM/DD
     */

    const slashMatch =
        text.match(
            /^(\d{4})\/(\d{2})\/(\d{2})/
        );

    if (slashMatch) {

        const date =
            new Date(
                Number(slashMatch[1]),
                Number(slashMatch[2]) - 1,
                Number(slashMatch[3])
            );

        if (
            !Number.isNaN(
                date.getTime()
            )
        ) {

            return date;
        }
    }


    /*
     * その他
     */

    const date =
        new Date(
            text
        );

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {

        return null;
    }

    return date;
}


// ======================================================
// X軸ラベル数調整
// ======================================================

function calculateLabelIndexes(
    count
) {

    if (count <= 6) {

        return Array.from(
            {
                length: count
            },
            (_, index) =>
                index
        );
    }

    const maxLabels = 7;

    const indexes = [];

    for (
        let i = 0;
        i < maxLabels;
        i++
    ) {

        const index =
            Math.round(
                i
                *
                (
                    count - 1
                )
                /
                (
                    maxLabels - 1
                )
            );

        indexes.push(
            index
        );
    }

    return [
        ...new Set(
            indexes
        )
    ];
}


// ======================================================
// グラフ空表示
// ======================================================

function drawGraphMessage(
    svg,
    message
) {

    const text =
        createSvgElement(
            "text",
            {
                x:
                    600,

                y:
                    300,

                class:
                    "graph-empty",

                "text-anchor":
                    "middle"
            }
        );

    text.textContent =
        message;

    svg.appendChild(
        text
    );
}


// ======================================================
// グラフツールチップ
// ======================================================

function buildPointTooltip(
    point
) {

    const game =
        point.game
        ||
        "大会名不明";

    const date =
        point.date
        ||
        "日付不明";

    const time =
        formatSeconds(
            point.seconds
        );

    return (
        date
        +
        " / "
        +
        game
        +
        " / "
        +
        time
    );
}


function showGraphTooltip(
    event,
    point
) {

    const tooltip =
        document.getElementById(
            "graphTooltip"
        );

    const wrapper =
        document.querySelector(
            ".graph-wrapper"
        );

    if (
        !tooltip
        ||
        !wrapper
    ) {
        return;
    }


    const game =
        point.game
        ||
        "大会名不明";

    const date =
        point.date
        ||
        "日付不明";

    const time =
        formatSeconds(
            point.seconds
        );


    tooltip.innerHTML =
        "<strong>"
        +
        escapeHtml(
            time
        )
        +
        "</strong><br>"
        +
        escapeHtml(
            date
        )
        +
        "<br>"
        +
        escapeHtml(
            game
        );


    tooltip.style.display =
        "block";


    /*
     * タップされた位置付近に表示。
     */

    const wrapperRect =
        wrapper.getBoundingClientRect();


    let x =
        event.clientX
        -
        wrapperRect.left
        +
        12;


    let y =
        event.clientY
        -
        wrapperRect.top
        -
        20;


    const maxX =
        wrapper.clientWidth
        -
        tooltip.offsetWidth
        -
        10;


    if (x > maxX) {
        x = maxX;
    }

    if (x < 10) {
        x = 10;
    }


    if (y < 10) {
        y = 10;
    }


    tooltip.style.left =
        x + "px";

    tooltip.style.top =
        y + "px";


    clearTimeout(
        window.graphTooltipTimer
    );


    window.graphTooltipTimer =
        setTimeout(
            () => {

                hideGraphTooltip();

            },
            4000
        );
}


function hideGraphTooltip() {

    const tooltip =
        document.getElementById(
            "graphTooltip"
        );

    if (!tooltip) {
        return;
    }

    tooltip.style.display =
        "none";
}


// ======================================================
// 秒 → 表示
// ======================================================

function formatSeconds(
    seconds
) {

    seconds =
        Number(
            seconds
        );

    if (
        !Number.isFinite(
            seconds
        )
    ) {
        return "-";
    }

    if (
        seconds >= 60
    ) {

        const minutes =
            Math.floor(
                seconds / 60
            );

        const remaining =
            seconds -
            minutes * 60;

        return (
            minutes
            +
            ":"
            +
            remaining
                .toFixed(2)
                .padStart(
                    5,
                    "0"
                )
        );
    }

    return Number(
        seconds
    ).toFixed(2);
}


// ======================================================
// HTMLエスケープ
// ======================================================

function escapeHtml(
    value
) {

    return String(
        value ?? ""
    )
    .replace(
        /&/g,
        "&amp;"
    )
    .replace(
        /</g,
        "&lt;"
    )
    .replace(
        />/g,
        "&gt;"
    )
    .replace(
        /"/g,
        "&quot;"
    )
    .replace(
        /'/g,
        "&#039;"
    );
}


// ======================================================
// Enterキー
// ======================================================

document
    .getElementById(
        "searchInput"
    )
    .addEventListener(
        "keydown",
        event => {

            if (
                event.key ===
                "Enter"
            ) {

                searchAthletes();
            }
        }
    );

</script>

</body>

</html>
"""


# =========================================================
# 起動
# =========================================================

if __name__ == "__main__":

    print()
    print("======================================")
    print(" SWIM MANAGER WEB APP")
    print("======================================")
    print()
    print("PC:")
    print("http://127.0.0.1:5001")
    print()
    print("同じWi-Fiのスマートフォンから使用する場合:")
    print("http://MacのIPアドレス:5001")
    print()
    print("======================================")

    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True
    )
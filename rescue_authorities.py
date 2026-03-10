"""USCG Rescue Coordination Centers (RCCs). Name -> phone for dropdown and auto-fill."""
# Source: USCG Office of Search and Rescue (RCC Numbers). Update as needed.

RCC_LIST = [
    ("", ""),
    ("USCG RCC Alameda", "(510) 437-3701"),
    ("USCG RCC Boston", "(617) 223-8555"),
    ("USCG RCC Cleveland", "(216) 902-6117"),
    ("USCG RCC Guam", "(671) 355-4824"),
    ("USCG RCC Honolulu", "(808) 535-3333"),
    ("USCG RCC Juneau", "(907) 463-2000"),
    ("USCG RCC Miami", "(305) 415-6800"),
    ("USCG RCC New Orleans", "(504) 589-6225"),
    ("USCG RCC Norfolk", "(757) 398-6231"),
    ("USCG RCC San Juan", "(787) 289-2042"),
    ("USCG RCC Seattle", "(206) 220-7001"),
]

RCC_NAMES = [name for name, _ in RCC_LIST]
RCC_PHONE_BY_NAME = {name: phone for name, phone in RCC_LIST}

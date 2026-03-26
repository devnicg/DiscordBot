import pycountry
import random
import re

# Manual overrides for names that pycountry might not fuzzy-match well
_OVERRIDES = {
    'democratic republic of congo': 'CD',
    'dr congo': 'CD',
    'drc': 'CD',
    'congo': 'CG',
    'republic of congo': 'CG',
    'usa': 'US',
    'uk': 'GB',
}

# Dominant non-black flag color per ISO alpha-2 code (as 0xRRGGBB int)
_FLAG_COLORS = {
    'AD': 0x003DA5, 'AE': 0x00732F, 'AF': 0xD32011, 'AG': 0xCE1126,
    'AL': 0xE41E20, 'AM': 0xD90012, 'AO': 0xCC0000, 'AR': 0x74ACDF,
    'AT': 0xED2939, 'AU': 0x00008B, 'AZ': 0x0092BC, 'BA': 0x002395,
    'BB': 0x00267F, 'BD': 0x006A4E, 'BE': 0xEF3340, 'BF': 0xEF2B2D,
    'BG': 0xD62612, 'BH': 0xCE1126, 'BI': 0xCE1126, 'BJ': 0x008751,
    'BN': 0xF7E017, 'BO': 0xD52B1E, 'BR': 0x009C3B, 'BS': 0x00778B,
    'BT': 0xFF8000, 'BW': 0x75AADB, 'BY': 0xCF101A, 'BZ': 0x003F87,
    'CA': 0xFF0000, 'CD': 0x007FFF, 'CF': 0x003082, 'CG': 0x009A44,
    'CH': 0xFF0000, 'CI': 0xF77F00, 'CL': 0xD52B1E, 'CM': 0x007A5E,
    'CN': 0xDE2910, 'CO': 0xFCD116, 'CR': 0x002B7F, 'CU': 0xCB1515,
    'CV': 0x003893, 'CY': 0x4E5B31, 'CZ': 0xD7141A, 'DE': 0xFFCE00,
    'DJ': 0x6AB2E7, 'DK': 0xC60C30, 'DM': 0x006B3F, 'DO': 0x002D62,
    'DZ': 0x006233, 'EC': 0xFFD100, 'EE': 0x0072CE, 'EG': 0xC8102E,
    'ER': 0x4189DD, 'ES': 0xAA151B, 'ET': 0x078930, 'FI': 0x003580,
    'FJ': 0x68BFE5, 'FM': 0x75B2DD, 'FR': 0x0055A4, 'GA': 0x009E60,
    'GB': 0x012169, 'GD': 0xCE1126, 'GE': 0xFF0000, 'GH': 0x006B3F,
    'GM': 0x3A7728, 'GN': 0xFCD116, 'GQ': 0x3E9A00, 'GR': 0x0D5EAF,
    'GT': 0x4997D0, 'GW': 0xCE1126, 'GY': 0x009E49, 'HN': 0x0073CF,
    'HR': 0xFF0000, 'HT': 0x00209F, 'HU': 0xCE2939, 'ID': 0xCE1126,
    'IE': 0x169B62, 'IL': 0x0038B8, 'IN': 0xFF9933, 'IQ': 0xCE1126,
    'IR': 0x239F40, 'IS': 0x003897, 'IT': 0x009246, 'JM': 0xFED100,
    'JO': 0x007A3D, 'JP': 0xBC002D, 'KE': 0x006600, 'KG': 0xE8112D,
    'KH': 0x032EA1, 'KI': 0xCE1126, 'KM': 0x3A75C4, 'KN': 0x009E60,
    'KP': 0x024FA2, 'KR': 0xCD2E3A, 'KW': 0x007A3D, 'KZ': 0x00AFCA,
    'LA': 0xCE1126, 'LB': 0xED1C24, 'LC': 0x65CFFF, 'LI': 0x002B7F,
    'LK': 0x8D153A, 'LR': 0xBF0A30, 'LS': 0x009543, 'LT': 0xFDB913,
    'LU': 0x00A3E0, 'LV': 0x9E3039, 'LY': 0x239E46, 'MA': 0xC1272D,
    'MC': 0xCE1126, 'MD': 0x003DA5, 'ME': 0xD4AF37, 'MG': 0xFC3D32,
    'MH': 0x003082, 'MK': 0xCE2028, 'ML': 0x009A00, 'MM': 0xFECB00,
    'MN': 0xC4272F, 'MR': 0x006233, 'MT': 0xCF142B, 'MU': 0xEA2839,
    'MV': 0xD21034, 'MW': 0x338E3E, 'MX': 0x006847, 'MY': 0xCC0001,
    'MZ': 0x009A44, 'NA': 0x003580, 'NE': 0xE05206, 'NG': 0x008751,
    'NI': 0x3E6EB4, 'NL': 0xAE1C28, 'NO': 0xEF2B2D, 'NP': 0x003893,
    'NR': 0x002B7F, 'NZ': 0x00247D, 'OM': 0xDB161B, 'PA': 0xDA121A,
    'PE': 0xD91023, 'PG': 0xE31B23, 'PH': 0x0038A8, 'PK': 0x01411C,
    'PL': 0xDC143C, 'PT': 0x006600, 'PW': 0x4AADD6, 'PY': 0xD52B1E,
    'QA': 0x8D1B3D, 'RO': 0x002B7F, 'RS': 0xC6363C, 'RU': 0xD52B1E,
    'RW': 0x20603D, 'SA': 0x006C35, 'SB': 0x0120B5, 'SC': 0x003F87,
    'SD': 0xD21034, 'SE': 0x006AA7, 'SG': 0xEF3340, 'SI': 0x003DA5,
    'SK': 0x0B4EA2, 'SL': 0x1EB53A, 'SM': 0x5EB6E4, 'SN': 0x00853F,
    'SO': 0x4189DD, 'SR': 0x377E3F, 'SS': 0x078930, 'ST': 0x12AD2B,
    'SV': 0x0F47AF, 'SY': 0xCE1126, 'SZ': 0x3E5EB9, 'TD': 0x002664,
    'TG': 0x006A4E, 'TH': 0xA51931, 'TJ': 0xCC0000, 'TL': 0xDC241F,
    'TM': 0x1C7A3E, 'TN': 0xE70013, 'TO': 0xC10000, 'TR': 0xE30A17,
    'TT': 0xCE1126, 'TV': 0x009FCA, 'TZ': 0x1EB53A, 'UA': 0x005BBB,
    'UG': 0xFCDC04, 'US': 0xB22234, 'UY': 0x5EB6E4, 'UZ': 0x1EB53A,
    'VA': 0xFFE000, 'VC': 0x009E60, 'VE': 0xCF142B, 'VN': 0xDA251D,
    'VU': 0x009543, 'WS': 0xCE1126, 'YE': 0xCE1126, 'ZA': 0x007A4D,
    'ZM': 0x198A00, 'ZW': 0x006400,
}


def _get_alpha2(country_name: str) -> str | None:
    name_lower = country_name.lower().strip()
    if name_lower in _OVERRIDES:
        return _OVERRIDES[name_lower]
    try:
        results = pycountry.countries.search_fuzzy(country_name)
        if results:
            return results[0].alpha_2
    except LookupError:
        pass
    return None


def _alpha2_to_flag(alpha2: str) -> str:
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in alpha2.upper())


def get_flag(country_name: str) -> str:
    alpha2 = _get_alpha2(country_name)
    if alpha2:
        return _alpha2_to_flag(alpha2)
    return '🏳️'


def get_flag_color(country_name: str) -> int:
    """Return a dominant non-black flag color for the country as 0xRRGGBB int.
    Falls back to a random saturated color if the country is not found."""
    alpha2 = _get_alpha2(country_name)
    if alpha2 and alpha2 in _FLAG_COLORS:
        return _FLAG_COLORS[alpha2]
    # Random fallback: avoid dark colors (each channel >= 80)
    return (random.randint(80, 255) << 16) | (random.randint(80, 255) << 8) | random.randint(80, 255)


def channel_safe_name(country_name: str) -> str:
    """Return lowercase, hyphenated country name safe for Discord channel names."""
    clean = country_name.lower().replace(' ', '-')
    clean = re.sub(r'[^a-z0-9\-]', '', clean)
    return clean.strip('-')


def country_channel_name(country_name: str) -> str:
    """Return 'country-name-🇧🇪' format for Discord channel/role names."""
    flag = get_flag(country_name)
    return f'{channel_safe_name(country_name)}-{flag}'

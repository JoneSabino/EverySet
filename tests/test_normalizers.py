"""Tests for all normalizer functions."""

from skins_extractor.normalizers.enums import normalize_role_type, normalize_union
from skins_extractor.normalizers.name import normalize_name
from skins_extractor.normalizers.phone import normalize_phone
from skins_extractor.normalizers.rate import parse_rate

# ── Phone normalizer ───────────────────────────────────────────────────────────


class TestNormalizePhone:
    def test_standard_dashes(self) -> None:
        assert normalize_phone("123-456-7890") == "123-456-7890"

    def test_dots(self) -> None:
        assert normalize_phone("123.456.7890") == "123-456-7890"

    def test_spaces(self) -> None:
        assert normalize_phone("123 456 7890") == "123-456-7890"

    def test_parens(self) -> None:
        assert normalize_phone("(818) 208-5757") == "818-208-5757"

    def test_11_digit_with_1(self) -> None:
        assert normalize_phone("18001234567") == "800-123-4567"

    def test_mixed_format(self) -> None:
        assert normalize_phone("122.334.5566") == "122-334-5566"

    def test_malformed_parens(self) -> None:
        # "777) 766-3666" — still 10 digits
        assert normalize_phone("777) 766-3666") == "777-766-3666"

    def test_empty(self) -> None:
        assert normalize_phone("") == ""

    def test_too_short(self) -> None:
        assert normalize_phone("12345") == ""

    def test_too_long_non_11(self) -> None:
        assert normalize_phone("123456789012") == ""


# ── Rate parser ───────────────────────────────────────────────────────────────


class TestParseRate:
    def test_simple_day_rate(self) -> None:
        r = parse_rate("$144/8")
        assert r.amount == 144.0
        assert r.unit == "day_8h"

    def test_no_dollar_sign(self) -> None:
        r = parse_rate("150/8")
        assert r.amount == 150.0
        assert r.unit == "day_8h"

    def test_hourly(self) -> None:
        r = parse_rate("$25/hr")
        assert r.amount == 25.0
        assert r.unit == "hourly"

    def test_voucher_only(self) -> None:
        r = parse_rate("VOUCHER")
        assert r.unit == "voucher"
        assert r.modifiers.get("voucher") is True

    def test_composite_with_bump(self) -> None:
        r = parse_rate("$224/8 + 250")
        assert r.amount == 224.0
        assert r.unit == "day_8h"
        assert r.modifiers.get("bump") == 250.0

    def test_voucher_plus_hourly_min(self) -> None:
        r = parse_rate("VOUCHER + $80/hr (min 4 hrs)")
        assert r.amount == 80.0
        assert r.unit == "hourly"
        assert r.modifiers.get("voucher") is True
        assert r.modifiers.get("min_hours") == 4

    def test_flat(self) -> None:
        r = parse_rate("$500 flat")
        assert r.amount == 500.0
        assert r.unit == "flat"

    def test_10h_day(self) -> None:
        r = parse_rate("$180/10")
        assert r.amount == 180.0
        assert r.unit == "day_10h"

    def test_12h_day(self) -> None:
        r = parse_rate("$200/12")
        assert r.amount == 200.0
        assert r.unit == "day_12h"

    def test_multiple_extras(self) -> None:
        r = parse_rate("$262/8 + $50 bump + $25 kit")
        assert r.amount == 262.0
        assert r.unit == "day_8h"
        extras = r.modifiers.get("extras", [])
        assert len(extras) == 2
        assert extras[0] == {"amount": 50.0, "label": "bump"}
        assert extras[1] == {"amount": 25.0, "label": "kit"}

    def test_named_fitting_extra(self) -> None:
        r = parse_rate("$144/8 + $50 fitting")
        assert r.amount == 144.0
        extras = r.modifiers.get("extras", [])
        assert extras[0] == {"amount": 50.0, "label": "fitting"}

    def test_guarantee(self) -> None:
        r = parse_rate("$500 guarantee")
        assert r.amount == 500.0
        assert r.unit == "flat"

    def test_empty(self) -> None:
        r = parse_rate("")
        assert r.amount is None
        assert r.unit == ""


# ── Name normalizer ───────────────────────────────────────────────────────────


class TestNormalizeName:
    def test_pass_through(self) -> None:
        assert normalize_name("Ralph Francisco") == "Ralph Francisco"

    def test_strip_leading_number(self) -> None:
        assert normalize_name("501 Ralph Francisco") == "Ralph Francisco"

    def test_last_first_comma(self) -> None:
        assert normalize_name("Francisco, Ralph") == "Ralph Francisco"

    def test_last_first_convention(self) -> None:
        assert (
            normalize_name("Francisco Ralph", column_convention="LAST FIRST") == "Ralph Francisco"
        )

    def test_empty(self) -> None:
        assert normalize_name("") == ""

    def test_strip_number_only(self) -> None:
        assert normalize_name("1 Janice Torno") == "Janice Torno"


# ── Enum normalizer ───────────────────────────────────────────────────────────


class TestNormalizeRoleType:
    def test_exact_background(self) -> None:
        rt, conf = normalize_role_type("BACKGROUND")
        assert rt == "background"
        assert conf >= 0.85

    def test_abbreviation_bg(self) -> None:
        rt, conf = normalize_role_type("BG")
        assert rt == "background"

    def test_stand_in(self) -> None:
        rt, conf = normalize_role_type("STAND INS")
        assert rt == "stand-in"

    def test_photo_double_pd(self) -> None:
        rt, conf = normalize_role_type("PD")
        assert rt == "photo double"

    def test_special_ability(self) -> None:
        rt, conf = normalize_role_type("SpA")
        assert rt == "special ability"

    def test_featured_background(self) -> None:
        rt, conf = normalize_role_type("featured bg")
        assert rt == "featured background"

    def test_no_match(self) -> None:
        rt, conf = normalize_role_type("ZZZZNOTAREALROLE")
        assert rt == ""
        assert conf == 0.0

    def test_fitting_no_match(self) -> None:
        # FITTING is not a role_type enum value
        rt, conf = normalize_role_type("FITTING")
        assert rt == ""


class TestNormalizeUnion:
    def test_sag(self) -> None:
        u, conf = normalize_union("SAG")
        assert u == "union"

    def test_non_union(self) -> None:
        u, conf = normalize_union("non-union")
        assert u == "non-union"

    def test_taft_hartley(self) -> None:
        u, conf = normalize_union("Taft Hartley")
        assert u == "non-union"

    def test_nu(self) -> None:
        u, conf = normalize_union("NU")
        assert u == "non-union"

    def test_empty(self) -> None:
        u, conf = normalize_union("")
        assert u == ""

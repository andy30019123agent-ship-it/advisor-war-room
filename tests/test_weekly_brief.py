"""每週下週劇本管線離線測試：純規則生成 + fixture daily.json，不打真實網路。"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from warroom import weekly_brief

_TPE = timezone(timedelta(hours=8))


def _daily(**overrides):
    base = {
        "meta": {"schema_version": 1, "data_date": "2026-07-17"},
        "market": {
            "status": "偏空防禦",
            "risk_temp": 9,
            "conclusion": "今天不加碼，守好停損位。",
        },
        "tracked": [
            {
                "id": "2330",
                "name": "台積電",
                "decision": {
                    "action": "續抱",
                    "readable_reason": "因為基本面沒惡化，所以續抱不動；但法人連日賣超是風險。",
                    "defense_price": 2106.8,
                },
            },
        ],
    }
    base.update(overrides)
    return base


def _write_daily(tmp_path, **overrides):
    p = tmp_path / "daily.json"
    p.write_text(json.dumps(_daily(**overrides), ensure_ascii=False), encoding="utf-8")
    return str(p)


# ── is_brief_day() ───────────────────────────────────────────────

@pytest.mark.parametrize("dt, expected", [
    (datetime(2026, 7, 19, 20, 0, tzinfo=_TPE), True),   # 週日
    (datetime(2026, 7, 18, 20, 0, tzinfo=_TPE), False),  # 週六
    (datetime(2026, 7, 20, 20, 0, tzinfo=_TPE), False),  # 週一
])
def test_is_brief_day(dt, expected):
    assert weekly_brief.is_brief_day(dt) is expected


# ── build_brief()：各區塊組裝 ──────────────────────────────────────

def test_build_brief_contains_all_sections_when_fields_present(tmp_path):
    daily = _daily(
        events=[{"date": "2026-07-22", "id": "2330", "name": "台積電", "type": "earnings", "label": "法說會"}],
        exposure_guidance={"risk_temp": 9, "note": "風險溫度 9/10：現金至少留六成，今天不開新倉。"},
    )
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))

    assert "📅 下週劇本" in msg
    assert "【上週收盤定位】" in msg
    assert "偏空防禦" in msg and "風險溫度 9/10" in msg
    assert "【本週事件】" in msg
    assert "07/22" in msg and "台積電" in msg and "法說會" in msg
    assert "【持股劇本】" in msg
    assert "台積電（2330）：續抱，防守價 2,106.8" in msg
    assert "【本週原則】" in msg
    assert "現金至少留六成" in msg


def test_build_brief_skips_events_section_when_field_absent(tmp_path):
    daily = _daily()  # 無 events 欄位
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "【本週事件】" not in msg
    # 其他區塊仍正常產出，不因缺欄位 crash
    assert "【上週收盤定位】" in msg
    assert "【持股劇本】" in msg


def test_build_brief_skips_events_section_when_empty_list(tmp_path):
    daily = _daily(events=[])
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "【本週事件】" not in msg


def test_build_brief_principle_falls_back_to_market_conclusion_without_exposure_guidance(tmp_path):
    daily = _daily()  # 無 exposure_guidance 欄位
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "【本週原則】" in msg
    assert "今天不加碼，守好停損位。" in msg.split("【本週原則】")[1]


def test_build_brief_holdings_uses_plan_first_item_when_stock_advice_present(tmp_path):
    stock_path = tmp_path / "2330.json"
    stock_path.write_text(json.dumps({
        "primary_decision": {
            "advice": {
                "holder": {
                    "action_text": "續抱不動，跌破 2,107 收盤再降一半波段部位。",
                    "plan": [
                        {"trigger": "收盤跌破 2,107（防守價）", "act": "賣出波段部位的 1/2"},
                    ],
                }
            }
        }
    }, ensure_ascii=False), encoding="utf-8")

    daily = _daily()
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "收盤跌破 2,107（防守價）→賣出波段部位的 1/2" in msg


def test_build_brief_holdings_falls_back_to_readable_reason_when_advice_missing(tmp_path):
    # stocks/2330.json 不存在（另一支管線還沒補齊 advice 欄位）→ 不 crash，退回 readable_reason 首句。
    daily = _daily()
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "台積電（2330）：續抱，防守價 2,106.8。因為基本面沒惡化，所以續抱不動" in msg


def test_build_brief_holdings_includes_week_range_70_line_when_forecast_present(tmp_path):
    stock_path = tmp_path / "2330.json"
    stock_path.write_text(json.dumps({
        "forecast": {"week_range_70": [2158.28, 2426.65]},
    }, ensure_ascii=False), encoding="utf-8")

    daily = _daily()
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "下週 70% 區間：2,158.3 ～ 2,426.7" in msg


def test_build_brief_holdings_skips_week_range_70_line_when_forecast_missing(tmp_path):
    # stocks/2330.json 不存在（forecast 樣本不足或另一支管線還沒補齊）→ 不 crash，不印該行
    daily = _daily()
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "下週 70% 區間" not in msg


def test_build_brief_holdings_skips_week_range_70_line_when_forecast_null(tmp_path):
    stock_path = tmp_path / "2330.json"
    stock_path.write_text(json.dumps({"forecast": None}, ensure_ascii=False), encoding="utf-8")
    daily = _daily()
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "下週 70% 區間" not in msg


def test_build_brief_holdings_skipped_when_tracked_empty(tmp_path):
    daily = _daily(tracked=[])
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert "【持股劇本】" not in msg


def test_build_brief_returns_none_when_daily_missing(tmp_path):
    assert weekly_brief.build_brief(None, stocks_dir=str(tmp_path)) is None
    assert weekly_brief.build_brief({}, stocks_dir=str(tmp_path)) is None


def test_build_brief_truncates_when_over_max_len(tmp_path):
    long_note = "很長的原則說明。" * 200
    daily = _daily(exposure_guidance={"note": long_note})
    msg = weekly_brief.build_brief(daily, stocks_dir=str(tmp_path))
    assert len(msg) <= weekly_brief.MAX_MESSAGE_LEN
    assert msg.endswith("…")


# ── run()：dry-run / 週日閘門 / graceful 缺檔 ───────────────────────

def test_run_dry_run_prints_brief_without_env(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    data_path = _write_daily(tmp_path)
    now = datetime(2026, 7, 19, 20, 0, tzinfo=_TPE)  # 週日

    rc = weekly_brief.run(data_path=data_path, stocks_dir=str(tmp_path), force=False, now=now)

    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "📅 下週劇本" in out
    assert "【持股劇本】" in out


def test_run_skips_on_non_sunday_without_force(tmp_path, monkeypatch):
    data_path = _write_daily(tmp_path)

    def _boom(*a, **kw):
        raise AssertionError("非週日不該送出")

    monkeypatch.setattr(weekly_brief, "send_telegram", _boom)
    now = datetime(2026, 7, 18, 20, 0, tzinfo=_TPE)  # 週六
    rc = weekly_brief.run(data_path=data_path, stocks_dir=str(tmp_path), force=False, now=now)
    assert rc == 0


def test_run_force_bypasses_sunday_gate(tmp_path, monkeypatch):
    data_path = _write_daily(tmp_path)
    sent = []
    monkeypatch.setattr(weekly_brief, "send_telegram", lambda msg, **kw: sent.append(msg) or True)
    now = datetime(2026, 7, 18, 20, 0, tzinfo=_TPE)  # 週六，但 --force
    rc = weekly_brief.run(data_path=data_path, stocks_dir=str(tmp_path), force=True, now=now)
    assert rc == 0
    assert len(sent) == 1


def test_run_missing_data_file_graceful(tmp_path, monkeypatch):
    missing_path = str(tmp_path / "does_not_exist.json")

    def _boom(*a, **kw):
        raise AssertionError("無資料不該嘗試送出")

    monkeypatch.setattr(weekly_brief, "send_telegram", _boom)
    now = datetime(2026, 7, 19, 20, 0, tzinfo=_TPE)
    rc = weekly_brief.run(data_path=missing_path, stocks_dir=str(tmp_path), force=True, now=now)
    assert rc == 0

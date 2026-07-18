"""到價提醒管線離線測試：全部 mock 即時價與 Telegram 呼叫，不打真實網路。"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from warroom import alerts

_TPE = timezone(timedelta(hours=8))


def _daily(snapshot):
    return {
        "meta": {"schema_version": 1, "data_date": "2026-07-18"},
        "alerts_snapshot": snapshot,
    }


def _write_daily(tmp_path, snapshot):
    p = tmp_path / "daily.json"
    p.write_text(json.dumps(_daily(snapshot), ensure_ascii=False), encoding="utf-8")
    return str(p)


# ── evaluate()：above/below 兩型觸發判斷 ──────────────────────────

def test_evaluate_defense_triggers_when_price_below():
    alert = {"id": "2330", "type": "defense", "price": 2245, "direction": "below"}
    assert alerts.evaluate(alert, 2238) is True


def test_evaluate_defense_not_triggered_when_price_above():
    alert = {"id": "2330", "type": "defense", "price": 2245, "direction": "below"}
    assert alerts.evaluate(alert, 2300) is False


def test_evaluate_entry_triggers_when_price_above():
    alert = {"id": "2454", "type": "entry", "price": 1200, "direction": "above"}
    assert alerts.evaluate(alert, 1250) is True


def test_evaluate_entry_not_triggered_when_price_below():
    alert = {"id": "2454", "type": "entry", "price": 1200, "direction": "above"}
    assert alerts.evaluate(alert, 1100) is False


def test_evaluate_none_price_never_triggers():
    alert = {"id": "2330", "type": "defense", "price": 2245}
    assert alerts.evaluate(alert, None) is False


# ── build_message()：訊息格式 ─────────────────────────────────────

def test_build_message_defense_zh():
    alert = {"id": "2330", "name": "台積電", "type": "defense", "price": 2245}
    msg = alerts.build_message(alert, 2238)
    assert msg == "⚠️ 台積電 2330 跌破防守價 2,245（現價 2,238）——照紀律先降波段部位，核心定期定額不動。"


def test_build_message_entry_zh():
    alert = {"id": "2454", "name": "聯發科", "type": "entry", "price": 1200}
    msg = alerts.build_message(alert, 1250)
    assert msg.startswith("🎯 聯發科 2454 觸發進場條件 1,200（現價 1,250）")


# ── run()：每日去重 ────────────────────────────────────────────────

def test_run_dedup_sends_once_per_day(tmp_path, monkeypatch):
    data_path = _write_daily(tmp_path, [
        {"id": "2330", "name": "台積電", "type": "defense", "price": 999999, "direction": "below"},
    ])
    state_path = str(tmp_path / "alerts_state.json")

    monkeypatch.setattr(alerts, "get_price", lambda sid: 2238)
    sent_msgs = []
    monkeypatch.setattr(alerts, "send_telegram", lambda msg, **kw: sent_msgs.append(msg) or True)

    now = datetime(2026, 7, 17, 10, 0, tzinfo=_TPE)  # 週五盤中
    alerts.run(data_path=data_path, state_path=state_path, force=True, now=now)
    alerts.run(data_path=data_path, state_path=state_path, force=True, now=now)

    assert len(sent_msgs) == 1
    state = json.loads(open(state_path, encoding="utf-8").read())
    assert "2330:defense:999999" in state["2026-07-17"]


def test_run_dedup_new_day_sends_again(tmp_path, monkeypatch):
    data_path = _write_daily(tmp_path, [
        {"id": "2330", "name": "台積電", "type": "defense", "price": 999999, "direction": "below"},
    ])
    state_path = str(tmp_path / "alerts_state.json")

    monkeypatch.setattr(alerts, "get_price", lambda sid: 2238)
    sent_msgs = []
    monkeypatch.setattr(alerts, "send_telegram", lambda msg, **kw: sent_msgs.append(msg) or True)

    day1 = datetime(2026, 7, 17, 10, 0, tzinfo=_TPE)
    day2 = datetime(2026, 7, 20, 10, 0, tzinfo=_TPE)
    alerts.run(data_path=data_path, state_path=state_path, force=True, now=day1)
    alerts.run(data_path=data_path, state_path=state_path, force=True, now=day2)

    assert len(sent_msgs) == 2


def test_run_not_triggered_no_send(tmp_path, monkeypatch):
    data_path = _write_daily(tmp_path, [
        {"id": "2330", "name": "台積電", "type": "defense", "price": 100, "direction": "below"},
    ])
    state_path = str(tmp_path / "alerts_state.json")

    monkeypatch.setattr(alerts, "get_price", lambda sid: 2238)  # 現價遠高於防守價 → 不觸發
    sent_msgs = []
    monkeypatch.setattr(alerts, "send_telegram", lambda msg, **kw: sent_msgs.append(msg) or True)

    now = datetime(2026, 7, 17, 10, 0, tzinfo=_TPE)
    alerts.run(data_path=data_path, state_path=state_path, force=True, now=now)
    assert sent_msgs == []


# ── graceful exit：無資料 / 非盤中 ──────────────────────────────────

def test_run_missing_data_file_graceful(tmp_path, monkeypatch):
    missing_path = str(tmp_path / "does_not_exist.json")
    state_path = str(tmp_path / "alerts_state.json")

    def _boom(sid):
        raise AssertionError("get_price 不該被呼叫（無資料應提早 return）")

    monkeypatch.setattr(alerts, "get_price", _boom)
    now = datetime(2026, 7, 17, 10, 0, tzinfo=_TPE)
    rc = alerts.run(data_path=missing_path, state_path=state_path, force=True, now=now)
    assert rc == 0


def test_run_outside_trading_hours_skips_without_force(tmp_path, monkeypatch):
    data_path = _write_daily(tmp_path, [
        {"id": "2330", "name": "台積電", "type": "defense", "price": 999999, "direction": "below"},
    ])
    state_path = str(tmp_path / "alerts_state.json")

    def _boom(sid):
        raise AssertionError("非盤中不該抓即時價")

    monkeypatch.setattr(alerts, "get_price", _boom)
    evening = datetime(2026, 7, 17, 20, 0, tzinfo=_TPE)  # 平日晚上，非盤中
    rc = alerts.run(data_path=data_path, state_path=state_path, force=False, now=evening)
    assert rc == 0


# ── is_trading_window() ────────────────────────────────────────────

@pytest.mark.parametrize("dt, expected", [
    (datetime(2026, 7, 17, 9, 0, tzinfo=_TPE), True),    # 週五 開盤瞬間
    (datetime(2026, 7, 17, 13, 30, tzinfo=_TPE), True),  # 週五 收盤瞬間
    (datetime(2026, 7, 17, 8, 59, tzinfo=_TPE), False),  # 開盤前
    (datetime(2026, 7, 17, 13, 31, tzinfo=_TPE), False), # 收盤後
    (datetime(2026, 7, 18, 10, 0, tzinfo=_TPE), False),  # 週六
    (datetime(2026, 7, 19, 10, 0, tzinfo=_TPE), False),  # 週日
])
def test_is_trading_window(dt, expected):
    assert alerts.is_trading_window(dt) is expected


# ── send_telegram() dry-run（無 env 時不打網路） ────────────────────

def test_send_telegram_dry_run_without_env(monkeypatch, capsys):
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TG_CHAT_ID", raising=False)

    def _boom(*a, **kw):
        raise AssertionError("dry-run 不該打網路")

    monkeypatch.setattr(alerts.urllib.request, "urlopen", _boom)
    ok = alerts.send_telegram("測試訊息")
    assert ok is True
    out = capsys.readouterr().out
    assert "[dry-run] 測試訊息" in out


# ── 去重輔助函式 ─────────────────────────────────────────────────

def test_alert_key_includes_price_so_changed_threshold_is_new_alert():
    a1 = {"id": "2330", "type": "defense", "price": 2245}
    a2 = {"id": "2330", "type": "defense", "price": 2200}
    assert alerts.alert_key(a1) != alerts.alert_key(a2)


def test_mark_sent_and_already_sent_roundtrip():
    state = {}
    key = "2330:defense:2245"
    assert alerts.already_sent(state, "2026-07-18", key) is False
    alerts.mark_sent(state, "2026-07-18", key)
    assert alerts.already_sent(state, "2026-07-18", key) is True


# ── fetch_price_twse()：tse_ 查無時 fallback otc_（2026-07-18 聯測 #5） ──────────

class _FakeTwseResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen_by_url_substring(responses):
    """responses: {url 裡要含的子字串: payload dict 或例外實例}。
    呼叫的 URL 沒有任何一個子字串命中就直接 assert 失敗，用來抓「呼叫了不該打的交易所」。"""

    def _fn(req, timeout=None):
        url = req.full_url
        for needle, val in responses.items():
            if needle in url:
                if isinstance(val, BaseException):
                    raise val
                return _FakeTwseResponse(val)
        raise AssertionError(f"未預期的 URL：{url}")

    return _fn


def test_fetch_price_twse_falls_back_to_otc_when_tse_has_no_data(monkeypatch):
    # 上櫃股（例如 6505）：tse_ 查無資料（msgArray 空），要接著試 otc_ 才拿得到價。
    responses = {
        "tse_6505.tw": {"msgArray": []},
        "otc_6505.tw": {"msgArray": [{"z": "81.30"}]},
    }
    monkeypatch.setattr(alerts.urllib.request, "urlopen", _fake_urlopen_by_url_substring(responses))
    assert alerts.fetch_price_twse("6505") == 81.30


def test_fetch_price_twse_prefers_tse_without_querying_otc(monkeypatch):
    # 上市股：tse_ 就查得到，不該多打一次 otc_（otc_ 沒在 responses 裡，打了就會 assert 失敗）。
    responses = {"tse_2330.tw": {"msgArray": [{"z": "1050.0"}]}}
    monkeypatch.setattr(alerts.urllib.request, "urlopen", _fake_urlopen_by_url_substring(responses))
    assert alerts.fetch_price_twse("2330") == 1050.0


def test_fetch_price_twse_both_exchanges_empty_returns_none(monkeypatch):
    responses = {
        "tse_9999.tw": {"msgArray": []},
        "otc_9999.tw": {"msgArray": []},
    }
    monkeypatch.setattr(alerts.urllib.request, "urlopen", _fake_urlopen_by_url_substring(responses))
    assert alerts.fetch_price_twse("9999") is None


def test_fetch_price_twse_tse_network_error_still_tries_otc(monkeypatch):
    # tse_ 連線失敗（不是「查無」，是真的斷線/逾時）也不該放棄，還是要試 otc_。
    responses = {
        "tse_6505.tw": OSError("timed out"),
        "otc_6505.tw": {"msgArray": [{"z": "81.30"}]},
    }
    monkeypatch.setattr(alerts.urllib.request, "urlopen", _fake_urlopen_by_url_substring(responses))
    assert alerts.fetch_price_twse("6505") == 81.30


def test_fetch_price_twse_both_exchanges_fail_raises(monkeypatch):
    # 兩個交易所都失敗才該真的往上丟例外，讓 get_price() 的既有 try/except 接手 fallback FinMind。
    responses = {
        "tse_6505.tw": OSError("timed out"),
        "otc_6505.tw": OSError("timed out"),
    }
    monkeypatch.setattr(alerts.urllib.request, "urlopen", _fake_urlopen_by_url_substring(responses))
    with pytest.raises(OSError):
        alerts.fetch_price_twse("6505")


def test_get_price_falls_back_to_finmind_when_both_twse_exchanges_empty(monkeypatch):
    # 端到端：tse_/otc_ 都查無 → get_price() 該接著打 FinMind fallback，不是直接放棄回 None。
    responses = {
        "tse_6505.tw": {"msgArray": []},
        "otc_6505.tw": {"msgArray": []},
    }
    monkeypatch.setattr(alerts.urllib.request, "urlopen", _fake_urlopen_by_url_substring(responses))
    monkeypatch.setattr(alerts, "fetch_price_finmind", lambda stock_id, **kw: 79.5)
    assert alerts.get_price("6505") == 79.5

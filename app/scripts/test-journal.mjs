// 純函式 assert 腳本：app 沒有 js 測試框架（package.json 沒有 vitest/jest），
// 用 node 直接跑（node app/scripts/test-journal.mjs）。Node 24 內建 TS type-stripping，
// 可以直接 import 真正的 ../src/lib/journal.ts（不是重寫一份邏輯去測，避免跟正式碼
// 邏輯漂移）。只測純函式（FIFO 配對／連敗／週覆盤），不碰 loadJournal/saveJournalEntry
// 這類會摸 localStorage 的（node 沒有 localStorage，也不需要測）。
//
// 涵蓋大檢查第 4 條：journal.ts 賣出配對改 per-stock FIFO 消耗庫存——多筆買進依序吃、
// 賣超出庫存的部分標 orphan（不算損益、不進連敗），連敗判定用 FIFO 損益。
import {
  findMatchingBuy,
  pairSells,
  getLossStreak,
  getStreakAlert,
  getWeeklyReview,
} from '../src/lib/journal.ts'
import { applyCooldown } from '../src/lib/cooldown.ts'

let pass = 0
let fail = 0

function assertEqual(actual, expected, label) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    pass++
  } else {
    fail++
    console.error(`FAIL: ${label}`)
    console.error(`  expected: ${JSON.stringify(expected)}`)
    console.error(`  actual:   ${JSON.stringify(actual)}`)
  }
}

function assertTrue(cond, label) {
  assertEqual(!!cond, true, label)
}

let seq = 0
function mk(side, stock_id, price, qty, day, overrides = {}) {
  seq += 1
  return {
    id: `e${seq}`,
    date: `2026-07-${String(day).padStart(2, '0')}`,
    stock_id,
    name: stock_id,
    side,
    price,
    qty,
    followed_advice: true,
    created_at: `T${String(seq).padStart(4, '0')}`,
    ...overrides,
  }
}

// ---------- Test 1：單一買進、單一賣出，完整配對（迴歸：舊行為的簡單 case 仍成立）----------
{
  const b1 = mk('buy', '2330', 100, 1000, 1)
  const s1 = mk('sell', '2330', 120, 1000, 5)
  const entries = [b1, s1]
  const paired = pairSells(entries)
  assertEqual(paired.length, 1, 'T1: 一筆賣出')
  assertEqual(paired[0].matchedQty, 1000, 'T1: matchedQty 全配到')
  assertEqual(paired[0].orphanQty, 0, 'T1: orphanQty=0')
  assertEqual(paired[0].pnlAmt, (120 - 100) * 1000, 'T1: pnl = (賣-買)*股數')
  assertEqual(paired[0].isLoss, false, 'T1: 賺錢不是虧損')
  assertEqual(findMatchingBuy(entries, s1)?.id, b1.id, 'T1: findMatchingBuy 配到那筆買進')
}

// ---------- Test 2：per-stock FIFO——一筆賣出跨吃兩筆不同價位的買進（先進先出）----------
{
  const b1 = mk('buy', '2454', 10, 100, 1) // 先買 100 股 @10
  const b2 = mk('buy', '2454', 12, 50, 2) // 再買 50 股 @12
  const s1 = mk('sell', '2454', 15, 120, 3) // 賣 120 股 @15：先吃 b1 全部 100，再吃 b2 的 20
  const entries = [b1, b2, s1]
  const paired = pairSells(entries)
  const r = paired[0]
  assertEqual(r.matchedQty, 120, 'T2: matchedQty=120（全配到，庫存剛好夠）')
  assertEqual(r.orphanQty, 0, 'T2: orphanQty=0')
  assertEqual(r.matches.length, 2, 'T2: 跨兩筆買進批次')
  assertEqual(r.matches[0], { buy: b1, qty: 100 }, 'T2: 先吃最舊的 b1 全部 100 股')
  assertEqual(r.matches[1], { buy: b2, qty: 20 }, 'T2: 再吃 b2 的 20 股（FIFO，不是 50 全吃）')
  const expectedPnl = (15 - 10) * 100 + (15 - 12) * 20
  assertEqual(r.pnlAmt, expectedPnl, 'T2: pnl 依各批次分別計算再加總（不是用單一買價）')
  assertEqual(r.isLoss, false, 'T2: 賺錢')
  assertEqual(r.buy?.id, b1.id, 'T2: buy 欄位相容舊介面＝FIFO 第一筆（最舊）')

  // b2 只被吃掉 20/50，剩 30 股庫存留給下一筆賣出繼續吃（驗證庫存真的有被扣減、不是每次都重算）
  const s2 = mk('sell', '2454', 20, 30, 4)
  const entries2 = [b1, b2, s1, s2]
  const paired2 = pairSells(entries2, [s2])
  assertEqual(paired2[0].matchedQty, 30, 'T2b: 第二筆賣出吃到 b2 剩下的 30 股')
  assertEqual(paired2[0].matches, [{ buy: b2, qty: 30 }], 'T2b: 只配到 b2（b1 已在 s1 被吃光）')
}

// ---------- Test 3：賣超庫存——超過部分標 orphan，不算損益、不進連敗 ----------
{
  const b1 = mk('buy', '2603', 10, 50, 1)
  const s1 = mk('sell', '2603', 9, 80, 2) // 只有 50 股庫存，卻賣 80 股
  const entries = [b1, s1]
  const paired = pairSells(entries)
  const r = paired[0]
  assertEqual(r.matchedQty, 50, 'T3: matchedQty=50（庫存上限）')
  assertEqual(r.orphanQty, 30, 'T3: orphanQty=30（賣超部分）')
  assertEqual(r.pnlAmt, (9 - 10) * 50, 'T3: pnl 只算 matched 的 50 股，orphan 30 股不算損益')
  assertEqual(r.isLoss, true, 'T3: matched 部位虧損 → isLoss=true')
}

// ---------- Test 4：完全配不到（沒有任何買進）→ orphan 全部，isLoss/pnlAmt 皆 null ----------
{
  const s1 = mk('sell', '2317', 100, 10, 1)
  const entries = [s1]
  const paired = pairSells(entries)
  const r = paired[0]
  assertEqual(r.matchedQty, 0, 'T4: matchedQty=0')
  assertEqual(r.orphanQty, 10, 'T4: orphanQty=全部')
  assertEqual(r.pnlAmt, null, 'T4: pnlAmt=null（無法判斷損益，不能算 0）')
  assertEqual(r.isLoss, null, 'T4: isLoss=null（不是 false，是不知道）')
  assertEqual(findMatchingBuy(entries, s1), null, 'T4: findMatchingBuy 找不到就回 null')
}

// ---------- Test 5：連敗判定用 FIFO 損益——orphan／win 都會中斷連敗計數 ----------
{
  const stock = '3008'
  const b = mk('buy', stock, 100, 300, 1) // 買 300 股，夠配 3 筆各 100 股的賣出
  const sLoss1 = mk('sell', stock, 90, 100, 2) // 虧
  const sLoss2 = mk('sell', stock, 80, 100, 3) // 虧
  const sLoss3 = mk('sell', stock, 70, 100, 4) // 虧（庫存正好用完：300 股全部配完）
  let entries = [b, sLoss1, sLoss2, sLoss3]
  assertEqual(getLossStreak(entries), 3, 'T5a: 連續 3 筆虧損（FIFO 都配得到成本）')
  assertEqual(getStreakAlert(entries).level, 'red', 'T5a: 連 3 筆 → red')

  // 在最新加一筆「配不到成本」的 orphan 賣出（庫存已空）：應該中斷連敗，不是繼續數
  const sOrphan = mk('sell', stock, 60, 50, 5)
  entries = [...entries, sOrphan]
  assertEqual(getLossStreak(entries), 0, 'T5b: 最新一筆是 orphan（isLoss=null）→ 連敗中斷歸零')
  assertEqual(getStreakAlert(entries).level, 'none', 'T5b: 中斷後 alert 回 none')

  // 換成賺錢的賣出也會中斷（用另一檔股票獨立驗證，避免庫存互相干擾）
  const stock2 = '2882'
  const b2a = mk('buy', stock2, 100, 300, 1)
  const loss1 = mk('sell', stock2, 90, 100, 2)
  const loss2 = mk('sell', stock2, 80, 100, 3)
  const win = mk('sell', stock2, 150, 100, 4)
  const entries2 = [b2a, loss1, loss2, win]
  assertEqual(getLossStreak(entries2), 0, 'T5c: 最新一筆賺錢 → 連敗歸零（不管前面兩筆虧損）')

  // 連續 2 筆虧損 → amber
  const stock3 = '6505'
  const b3 = mk('buy', stock3, 100, 200, 1)
  const l1 = mk('sell', stock3, 95, 100, 2)
  const l2 = mk('sell', stock3, 90, 100, 3)
  const entries3 = [b3, l1, l2]
  assertEqual(getStreakAlert(entries3).level, 'amber', 'T5d: 連續 2 筆虧損 → amber')
}

// ---------- Test 6：週覆盤 realizedPnl 只加總 matched 部位，且用完整歷史模擬 FIFO（買在週期外也算）----------
{
  const stock = '2412'
  // 買進在「本週之前」（用很早的日期＋固定 now），賣出落在本週
  const buyEarly = { ...mk('buy', stock, 20, 100, 1), date: '2020-01-01' }
  const now = new Date('2026-07-16T09:00:00+08:00') // 週四，週範圍 2026-07-13~07-19
  const sellThisWeek = { ...mk('sell', stock, 25, 100, 2), date: '2026-07-15' }
  const entries = [buyEarly, sellThisWeek]
  const review = getWeeklyReview(entries, now)
  assertEqual(review.sellCount, 1, 'T6a: 本週賣出 1 筆')
  assertEqual(review.realizedPnl, (25 - 20) * 100, 'T6a: realizedPnl 用完整歷史 FIFO 配到週期外的買進')

  // 本週唯一一筆賣出完全配不到成本（orphan）→ realizedPnl 該是 null，不是 0
  const stock2 = '2884'
  const sellOrphanOnly = { ...mk('sell', stock2, 30, 10, 2), date: '2026-07-14' }
  const review2 = getWeeklyReview([sellOrphanOnly], now)
  assertEqual(review2.realizedPnl, null, 'T6b: 唯一一筆賣出是 orphan → realizedPnl=null（不能顯示 0）')
}

// ---------- Test 7：冷靜期落地（applyCooldown，契約 v1.6 執行鏈路節）----------
{
  const none = applyCooldown(200000, 0)
  assertEqual(none, { level: 'none', amount: 200000, badgeText: null }, 'T7a: streak=0 → none，金額原封不動')

  const one = applyCooldown(200000, 1)
  assertEqual(one, { level: 'none', amount: 200000, badgeText: null }, 'T7b: streak=1 → 還沒觸發，仍是 none')

  const amber = applyCooldown(200000, 2)
  assertEqual(amber, { level: 'amber', amount: 100000, badgeText: '冷靜期' }, 'T7c: streak=2 → amber，金額減半')

  const red = applyCooldown(200000, 3)
  assertEqual(red, { level: 'red', amount: null, badgeText: '暫停新倉' }, 'T7d: streak=3 → red，金額改用暫停新倉文字取代')

  const redAbove = applyCooldown(200000, 5)
  assertEqual(redAbove.level, 'red', 'T7e: streak>3 一樣是 red（不會回退）')
}

console.log(`\n${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

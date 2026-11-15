const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const base = process.env.BASE, pw = process.env.PASSWORD, out = process.env.OUT;
  async function session(user) {
    const ctx = await b.newContext({ viewport: { width: 1180, height: 760 } }); const p = await ctx.newPage();
    await p.goto(base + '/'); await p.selectOption('#u', user); await p.fill('#p', pw); await p.click('#go'); await p.waitForSelector('#app:not([hidden])');
    await p.waitForTimeout(400); return p;
  }
  const tab = async (p, name) => { await p.click(`#tabs button[data-t="${name}"]`); await p.waitForTimeout(500); };
  let p = await session('fm'); await p.screenshot({ path: out + '/01_dashboard.png' });
  await tab(p, 'Tickets'); await p.click(`.tv[data-t="${process.env.TID}"]`); await p.waitForTimeout(600); await p.screenshot({ path: out + '/03_ticket_detail.png', fullPage: true });
  await tab(p, 'Audit'); await p.screenshot({ path: out + '/05_audit.png' });
  p = await session('faculty1'); await tab(p, 'Facilities & Bookings');
  await p.selectOption('#bf', '2'); await p.fill('#bs', '2026-11-20T09:00'); await p.fill('#be', '2026-11-20T11:00'); await p.click('#bgo'); await p.waitForTimeout(500);
  p.close(); p = await session('faculty2'); await tab(p, 'Facilities & Bookings');
  await p.selectOption('#bf', '2'); await p.fill('#bs', '2026-11-20T10:00'); await p.fill('#be', '2026-11-20T12:00'); await p.click('#bgo'); await p.waitForTimeout(600);
  await p.screenshot({ path: out + '/02_booking_overlap_rejected.png' });
  p = await session('approver'); await tab(p, 'Approvals & Loans'); await p.screenshot({ path: out + '/04_approvals.png' });
  p = await session('student1'); await tab(p, 'Tickets'); await p.click(`.tv[data-t="${process.env.TID}"]`); await p.waitForTimeout(500);
  await p.click('.tt[data-a="close"]'); await p.waitForTimeout(500); await p.evaluate(() => window.scrollTo(0, 0)); await p.screenshot({ path: out + '/06_unauthorised_close.png', clip: { x: 0, y: 0, width: 1180, height: 200 } });
  await b.close(); console.log('ok');
})().catch(e => { console.error(String(e)); process.exit(1); });

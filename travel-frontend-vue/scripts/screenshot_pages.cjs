/**
 * CDP screenshots for authed app pages.
 * Usage: node screenshot_pages.cjs / /generate /trips
 */
const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')
const http = require('http')

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const APP = 'http://localhost:5173'
const PORT = 9224
const OUTDIR = path.join(__dirname, '..', 'src', 'assets', 'img')

function getJson(pathname) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port: PORT, path: pathname }, (res) => {
      let d = ''
      res.on('data', (c) => (d += c))
      res.on('end', () => {
        try {
          resolve(JSON.parse(d))
        } catch (e) {
          reject(e)
        }
      })
    })
    req.on('error', reject)
  })
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  const routes = process.argv.slice(2)
  if (!routes.length) throw new Error('pass routes')

  const chrome = spawn(
    CHROME,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--remote-debugging-port=' + PORT,
      '--window-size=1280,1000',
      'about:blank',
    ],
    { stdio: 'ignore' }
  )

  let page = null
  for (let i = 0; i < 50; i++) {
    try {
      const list = await getJson('/json/list')
      page = list.find((t) => t.type === 'page')
      if (page) break
    } catch {
      /* retry */
    }
    await sleep(200)
  }
  if (!page) {
    chrome.kill()
    throw new Error('no page')
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()

  function send(method, params = {}) {
    const msgId = ++id
    return new Promise((resolve, reject) => {
      pending.set(msgId, { resolve, reject })
      ws.send(JSON.stringify({ id: msgId, method, params }))
    })
  }

  await new Promise((resolve, reject) => {
    ws.onopen = resolve
    ws.onerror = reject
  })
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      if (msg.error) reject(new Error(msg.error.message))
      else resolve(msg.result)
    }
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: APP + '/' })
  await sleep(600)
  await send('Runtime.evaluate', {
    expression: `localStorage.setItem('token','dev-preview-token');localStorage.setItem('username','预览用户');localStorage.setItem('role','user');`,
  })

  for (const route of routes) {
    await send('Page.navigate', { url: APP + route })
    await sleep(2200)
    const name = 'preview-' + (route === '/' ? 'home' : route.replace(/\//g, '-').replace(/^-/, '')) + '.png'
    const out = path.join(OUTDIR, name)
    const shot = await send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(out, Buffer.from(shot.data, 'base64'))
    console.log('saved', name, fs.statSync(out).size)
  }

  ws.close()
  chrome.kill()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})

import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const BASE_MODES = ['UNCONFIGURED', 'INPUT', 'INPUT_PULLUP', 'INPUT_PULLDOWN', 'OUTPUT', 'PWM', 'ADC']

function riskLabel(risk = '') {
  const map = {
    strapping: 'BOOT STRAP',
    'strapping-led': 'LED / STRAP',
    'strapping-boot': 'BOOT / STRAP',
    'strapping-vddspi': 'VDD_SPI STRAP',
    'strapping-input-only': 'INPUT / STRAP',
    'native-usb': 'NATIVE USB',
    'reserved-octal-psram': 'PSRAM LOCK',
    'reserved-if-octal': 'MEMORY LOCK',
    'uart-rx': 'UART RX',
    'uart-tx': 'UART TX',
    jtag: 'JTAG',
    'rgb-led': 'RGB LED',
    'rgb-led-v1.0': 'RGB v1.0',
    'rgb-led-v1.1': 'RGB v1.1',
    'rgb-led-possible': 'RGB / CHECK',
    adc2: 'ADC2'
  }
  return map[risk] || risk.replaceAll('-', ' ').toUpperCase()
}

function Toast({ toast, onClose }) {
  if (!toast) return null
  return <div className={`toast ${toast.type || 'ok'}`} onClick={onClose}>{toast.message}</div>
}

function Metric({ label, value, sub, tone = '' }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  )
}

function BoardBadge({ profile, compact = false }) {
  if (!profile) return null
  const mem = profile.memory || {}
  return (
    <div className={`board-badge ${compact ? 'compact' : ''}`}>
      <span className="board-soc">{profile.family?.replace('ESP32-', '') || profile.chip?.replace('esp32', '').toUpperCase()}</span>
      <div>
        <strong>{profile.name}</strong>
        <small>{mem.flash_mb ? `${mem.flash_mb}MB flash` : 'flash ?'}{mem.psram_mb ? ` · ${mem.psram_mb}MB PSRAM ${mem.psram_mode || ''}` : ''}</small>
      </div>
      <span className={`verify-dot ${profile.verified ? 'verified' : ''}`} title={profile.verified ? 'Reference/profile verified' : 'Clone profile: verify pinout'} />
    </div>
  )
}

function PinCard({ pin, onMode, onWrite, onPwm }) {
  const [duty, setDuty] = useState(pin.duty_u16 || 0)
  const [frequency, setFrequency] = useState(pin.frequency || 1000)

  useEffect(() => {
    setDuty(pin.duty_u16 || 0)
    setFrequency(pin.frequency || 1000)
  }, [pin.duty_u16, pin.frequency])

  const allowedModes = BASE_MODES.filter((mode) => {
    if (!pin.available && mode !== 'UNCONFIGURED') return false
    if (mode === 'ADC' && !pin.adc) return false
    if (mode === 'PWM' && !pin.pwm) return false
    if (mode === 'OUTPUT' && !pin.output) return false
    return true
  })
  const percent = Math.round((duty / 65535) * 100)

  const changeMode = (mode) => {
    if (pin.danger && mode !== 'UNCONFIGURED') {
      const ok = window.confirm(`GPIO${pin.gpio}: ${pin.note || 'этот пин может влиять на загрузку, USB или память.'}\n\nПрименить ${mode} принудительно?`)
      if (!ok) return
      onMode(pin.gpio, mode, true)
      return
    }
    onMode(pin.gpio, mode, false)
  }

  return (
    <article className={`pin-card ${!pin.available ? 'locked' : ''} ${pin.danger ? 'danger-pin' : ''} ${pin.error ? 'has-error' : ''}`}>
      <header>
        <div>
          <span className="pin-number">GPIO {pin.gpio}</span>
          <h3>{pin.label}</h3>
          {pin.aliases?.length > 0 && <small className="aliases">{pin.aliases.join(' · ')}</small>}
        </div>
        <div className="badge-stack">
          {!pin.available && <span className="badge lock">LOCKED</span>}
          {pin.risk && <span className={`badge ${pin.danger ? 'danger' : 'warning'}`}>{riskLabel(pin.risk)}</span>}
        </div>
      </header>

      <label className="field compact">
        <span>Режим</span>
        <select value={pin.mode} onChange={(event) => changeMode(event.target.value)} disabled={!pin.available && pin.mode === 'UNCONFIGURED'}>
          {allowedModes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
        </select>
      </label>

      {pin.mode === 'OUTPUT' && (
        <div className="pin-control-row">
          <span>Уровень</span>
          <button className={`switch ${pin.value ? 'on' : ''}`} onClick={() => onWrite(pin.gpio, pin.value ? 0 : 1)}><span /></button>
          <strong>{pin.value ? 'HIGH' : 'LOW'}</strong>
        </div>
      )}

      {['INPUT', 'INPUT_PULLUP', 'INPUT_PULLDOWN'].includes(pin.mode) && (
        <div className="reading digital"><span>Digital</span><strong>{pin.value ?? '—'}</strong></div>
      )}

      {pin.mode === 'ADC' && <div className="reading"><span>ADC / 16-bit</span><strong>{pin.value ?? '—'}</strong></div>}

      {pin.mode === 'PWM' && (
        <div className="pwm-box">
          <div className="range-title"><span>Duty</span><strong>{percent}%</strong></div>
          <input type="range" min="0" max="65535" value={duty}
            onChange={(event) => setDuty(Number(event.target.value))}
            onPointerUp={() => onPwm(pin.gpio, duty, frequency)}
            onKeyUp={() => onPwm(pin.gpio, duty, frequency)} />
          <label className="field compact"><span>Частота, Hz</span><input type="number" min="1" max="1000000" value={frequency}
            onChange={(event) => setFrequency(Number(event.target.value))}
            onBlur={() => onPwm(pin.gpio, duty, frequency)} /></label>
        </div>
      )}

      {pin.mode === 'UNCONFIGURED' && <p className="muted small">{pin.available ? 'Пин свободен и не захвачен runtime.' : 'Пин заблокирован профилем платы.'}</p>}
      {pin.note && <p className="pin-note">{pin.note}</p>}
      {pin.error && <p className="error-text">{pin.error}</p>}
    </article>
  )
}

function GpioTab({ status, deviceInfo, refresh, notify }) {
  const [filter, setFilter] = useState('all')
  const [liveAction, setLiveAction] = useState(null)
  const pins = status?.pins || []
  const visible = pins.filter((pin) => {
    if (filter === 'safe') return pin.available && !pin.danger && !pin.risk
    if (filter === 'attention') return pin.available && (pin.danger || pin.risk)
    if (filter === 'locked') return !pin.available
    return true
  })

  const act = async (fn, success, label = 'GPIO command') => {
    setLiveAction({ label, state: 'running' })
    try {
      await fn()
      await refresh()
      setLiveAction({ label, state: 'done' })
      window.setTimeout(() => setLiveAction(null), 900)
      if (success) notify(success)
    } catch (error) {
      setLiveAction({ label, state: 'error' })
      window.setTimeout(() => setLiveAction(null), 1800)
      notify(error.message, 'error')
    }
  }

  return (
    <section>
      <div className="section-heading split-heading">
        <div>
          <p className="eyebrow">LIVE GPIO MATRIX</p>
          <h2>{deviceInfo?.board || 'Пины подключённой платы'}</h2>
          <p>Видны только GPIO из профиля, записанного на контроллер. Опасные и занятые памятью пины помечаются отдельно.</p>
        </div>
        <div className="heading-actions">
          <div className="segmented">
            {['all', 'safe', 'attention', 'locked'].map((item) => (
              <button key={item} className={filter === item ? 'active' : ''} onClick={() => setFilter(item)}>
                {item === 'all' ? 'Все' : item === 'safe' ? 'Safe' : item === 'attention' ? 'Risk' : 'Locked'}
              </button>
            ))}
          </div>
          {liveAction && <span className={`live-command ${liveAction.state}`}><i />{liveAction.state === 'running' ? 'Выполняется' : liveAction.state === 'done' ? 'Готово' : 'Ошибка'} · {liveAction.label}</span>}
          <button className="secondary" onClick={refresh}>Обновить</button>
        </div>
      </div>
      <div className="pin-grid">
        {visible.map((pin) => (
          <PinCard key={pin.gpio} pin={pin}
            onMode={(gpio, mode, force) => act(() => api.setMode(gpio, mode, force), '', `GPIO${gpio} → ${mode}`)}
            onWrite={(gpio, value) => act(() => api.writePin(gpio, value), '', `GPIO${gpio} → ${value ? 'HIGH' : 'LOW'}`)}
            onPwm={(gpio, duty, frequency) => act(() => api.pwm(gpio, duty, frequency), '', `GPIO${gpio} PWM`)} />
        ))}
      </div>
    </section>
  )
}


function JobProgress({ job, compact = false }) {
  if (!job) return null
  const done = job.status === 'done'
  const failed = job.status === 'error'
  return (
    <div className={`job-progress ${compact ? 'compact' : ''} ${failed ? 'failed' : ''} ${done ? 'done' : ''}`}>
      <div className="job-progress-head">
        <div><p className="eyebrow">LIVE JOB</p><strong>{job.title}</strong><small>{job.message || (job.status === 'running' ? 'Выполняется…' : job.status)}</small></div>
        <div className="job-percent">{job.progress}%</div>
      </div>
      <div className="progress-track"><span style={{ width: `${job.progress}%` }} /></div>
      <div className="stage-grid">
        {(job.stages || []).map((stage, index) => (
          <div key={stage.id} className={`stage-cell ${stage.status}`}>
            <span className="stage-index">{String(index + 1).padStart(2, '0')}</span>
            <div><b>{stage.label}</b><small>{stage.detail || (stage.status === 'pending' ? 'ожидание' : stage.status)}</small></div>
            <strong>{stage.status === 'done' ? '✓' : stage.status === 'error' ? '!' : stage.progress == null ? '…' : `${stage.progress}%`}</strong>
          </div>
        ))}
      </div>
      {job.error && <div className="alert error job-error">{job.error}</div>}
    </div>
  )
}

function useJobRunner(notify) {
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)

  const runJob = async (starter, onDone) => {
    setBusy(true)
    try {
      const started = await starter()
      const jobId = started.job_id
      while (true) {
        const current = await api.job(jobId)
        setJob(current)
        if (current.status === 'done') {
          notify(current.result?.message || current.message || 'Готово')
          if (onDone) await onDone(current.result || {}, current)
          return current.result || {}
        }
        if (current.status === 'error') {
          notify(current.error || 'Ошибка операции', 'error')
          return null
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250))
      }
    } catch (error) {
      notify(error.message, 'error')
      setJob((current) => current || { title: 'Операция', status: 'error', progress: 0, stages: [], error: error.message })
      return null
    } finally {
      setBusy(false)
    }
  }

  return { job, busy, runJob, setJob }
}

function FilesTab({ notify, openHistory }) {
  const [files, setFiles] = useState([])
  const [path, setPath] = useState('/main.py')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [wifiSsid, setWifiSsid] = useState('')
  const [wifiPassword, setWifiPassword] = useState('')
  const [message, setMessage] = useState('Save from Wi-Fi editor')
  const { job, busy: jobBusy, runJob, setJob } = useJobRunner(notify)

  const loadList = async () => {
    try {
      const data = await api.files('/')
      setFiles(data.items || [])
    } catch (error) { notify(error.message, 'error') }
  }
  useEffect(() => { loadList() }, [])

  const openFile = async (filePath) => {
    if (!filePath || filePath.endsWith('/')) return
    setBusy(true)
    try { setPath(filePath); setContent(await api.readFile(filePath)) }
    catch (error) { notify(error.message, 'error') }
    finally { setBusy(false) }
  }

  const save = async () => {
    const result = await runJob(() => api.startSaveFile(path, content, message))
    if (result) await loadList()
  }

  return (
    <section className="workspace-grid">
      <aside className="panel file-list-panel">
        <div className="panel-title"><div><p className="eyebrow">WI‑FI PROGRAMMING</p><h2>Файлы устройства</h2></div><button className="icon-button" onClick={loadList}>↻</button></div>
        <div className="history-hint"><span>●</span><div><b>Local History включён</b><small>Версия создаётся при каждом сохранении. config.json и секреты не архивируются.</small></div></div>
        <div className="file-list">
          {files.map((file) => (
            <button key={file.path} disabled={file.directory} onClick={() => openFile(file.path)} className={path === file.path ? 'selected' : ''}>
              <span>{file.directory ? '▸' : '•'} {file.name}</span><small>{file.directory ? 'DIR' : `${file.size || 0} B`}</small>
            </button>
          ))}
        </div>
        <label className="field"><span>Путь</span><input value={path} onChange={(e) => setPath(e.target.value)} /></label>
        <button className="secondary full-button" onClick={() => openHistory(path)}>Версии этого файла</button>
      </aside>

      <div className="panel editor-panel">
        <div className="panel-title"><div><p className="eyebrow">EDITOR</p><h2>{path}</h2></div><div className="button-row"><button className="danger ghost" onClick={async () => {
          if (!window.confirm(`Удалить ${path}? Предыдущая версия останется в Local History.`)) return
          const result = await runJob(() => api.startDeleteFile(path)); if (result) { setContent(''); await loadList() }
        }}>Удалить</button><button onClick={save} disabled={busy || jobBusy}>{jobBusy ? 'Операция…' : 'Сохранить по Wi‑Fi'}</button></div></div>
        <textarea className="code-editor" spellCheck="false" value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="editor-meta-row"><label className="field"><span>Комментарий версии</span><input value={message} onChange={(e) => setMessage(e.target.value)} /></label><span className="history-badge">AUTO VERSION</span></div>
        <JobProgress job={job} compact />
        <div className="button-row bottom-actions"><button className="secondary" onClick={async () => {
          await runJob(() => api.startReboot())
        }}>Перезагрузить ESP32</button></div>
      </div>

      <div className="panel wifi-panel">
        <p className="eyebrow">NETWORK</p><h2>Сменить Wi‑Fi</h2>
        <div className="form-grid"><label className="field"><span>SSID</span><input value={wifiSsid} onChange={(e) => setWifiSsid(e.target.value)} /></label><label className="field"><span>Пароль</span><input type="password" value={wifiPassword} onChange={(e) => setWifiPassword(e.target.value)} /></label></div>
        <button onClick={async () => {
          await runJob(() => api.startWifi(wifiSsid, wifiPassword))
        }}>Сохранить сеть</button>
        <div className="alert warn secrets-note">Wi‑Fi пароль и API token не попадают в Local History и Cloud Sync.</div>
      </div>
    </section>
  )
}

function ProfileDetails({ profile, probe }) {
  if (!profile) return <div className="empty-mini">Выберите профиль платы.</div>
  const mem = profile.memory || {}
  const locked = profile.pins?.filter((p) => !p.available).length || 0
  const risk = profile.pins?.filter((p) => p.danger).length || 0
  const chipMismatch = probe?.chip && probe.chip !== profile.chip
  return (
    <div className={`profile-details ${chipMismatch ? 'mismatch' : ''}`}>
      <BoardBadge profile={profile} />
      <p>{profile.description}</p>
      <div className="profile-stats">
        <span><b>{profile.pins?.length || 0}</b> GPIO entries</span>
        <span><b>{risk}</b> protected</span>
        <span><b>{locked}</b> locked</span>
        <span><b>{mem.psram_mode || 'none'}</b> PSRAM mode</span>
      </div>
      {chipMismatch && <div className="alert error">Профиль ожидает {profile.chip}, а probe обнаружил {probe.chip}. Прошивка будет заблокирована.</div>}
      {!profile.verified && <div className="alert warn">Это профиль семейства/клона. Перед подключением нагрузки сравните GPIO с маркировкой именно вашей платы.</div>}
      {profile.notes?.length > 0 && <ul className="note-list">{profile.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </div>
  )
}

function UsbBoardTab({ notify, profiles }) {
  const [ports, setPorts] = useState([])
  const [port, setPort] = useState('')
  const [profileId, setProfileId] = useState(profiles[0]?.id || '')
  const [probe, setProbe] = useState(null)
  const [ssid, setSsid] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState('')
  const { job, busy, runJob, setJob } = useJobRunner(notify)

  useEffect(() => { if (!profileId && profiles.length) setProfileId(profiles[0].id) }, [profiles, profileId])
  const selectedProfile = profiles.find((p) => p.id === profileId)

  const refreshPorts = async () => {
    try {
      const data = await api.ports()
      setPorts(data.ports || [])
      if (!port && data.ports?.length) setPort(data.ports[0].device)
    } catch (error) { notify(error.message, 'error') }
  }
  useEffect(() => { refreshPorts() }, [])

  const requirePort = () => {
    if (!port) { notify('Выберите COM-порт', 'error'); return false }
    return true
  }

  const doProbe = async () => {
    if (!requirePort()) return
    await runJob(() => api.startProbe(port), async (result) => setProbe(result))
  }

  const generateToken = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(18))
    setToken(Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(''))
  }
  const compatibleIds = new Set(probe?.compatible_profiles?.map((p) => p.id) || [])

  return (
    <section className="usb-board-layout">
      <div className="panel board-selector-panel">
        <div className="panel-title"><div><p className="eyebrow">BOARD DISCOVERY</p><h2>COM + профиль платы</h2></div><button className="secondary" onClick={refreshPorts}>COM ↻</button></div>
        <div className="two-col">
          <label className="field"><span>COM-порт</span><select value={port} onChange={(e) => { setPort(e.target.value); setProbe(null); setJob(null) }}><option value="">— выберите —</option>{ports.map((item) => <option key={item.device} value={item.device}>{item.device} — {item.description || item.manufacturer}</option>)}</select></label>
          <div className="probe-action"><button className="scan-button" disabled={busy || !port} onClick={doProbe}><span>⌁</span> Определить чип</button></div>
        </div>

        {probe ? (
          <div className="probe-result">
            <div><span className="probe-chip">{probe.chip_text || probe.chip}</span><small>{probe.port}</small></div>
            <div className="probe-facts"><span>FLASH <b>{probe.flash_mb ? `${probe.flash_mb} MB` : '—'}</b></span><span>PSRAM <b>{probe.psram_mb ? `${probe.psram_mb} MB` : 'profile'}</b></span><span>MAC <b>{probe.mac || '—'}</b></span></div>
          </div>
        ) : <div className="probe-placeholder">`esptool flash-id` определит семейство SoC и размер flash. Точную модель клона выбираем профилем.</div>}

        <div className="profile-picker-head"><div><p className="eyebrow">BOARD PROFILES</p><h3>Выберите разводку</h3></div><span>{profiles.length} профилей</span></div>
        <div className="profile-cards">
          {profiles.map((profile) => {
            const recommended = probe && compatibleIds.has(profile.id)
            return (
              <button key={profile.id} className={`profile-card ${profileId === profile.id ? 'selected' : ''} ${recommended ? 'compatible' : ''}`} onClick={() => setProfileId(profile.id)}>
                <BoardBadge profile={profile} compact />
                <span className="profile-desc">{profile.description}</span>
                <span className="profile-footer">{recommended ? 'совместим с probe' : profile.verified ? 'reference profile' : 'clone / custom'}</span>
              </button>
            )
          })}
        </div>
        <ProfileDetails profile={selectedProfile} probe={probe} />
      </div>

      <div className="panel install-panel">
        <p className="eyebrow">FLASH & PROVISION</p><h2>Установка</h2>
        <JobProgress job={job} />
        <div className="step-card">
          <span className="step-num">01</span><div className="grow"><h3>MicroPython v1.28.0</h3><p>Теперь процесс виден по этапам: Probe → Firmware → Erase → Flash → Verify. Процент Flash берётся из реального вывода esptool.</p><button className="danger" disabled={busy || !profileId} onClick={() => {
            if (!requirePort()) return
            if (!window.confirm(`Erase + flash ${selectedProfile?.name || profileId}? Текущая файловая система будет удалена.`)) return
            runJob(() => api.startFlash(port, profileId, true, 460800), async (result) => { if (result?.probe) setProbe(result.probe) })
          }}>Erase + Flash</button></div>
        </div>
        <div className="step-card">
          <span className="step-num">02</span><div className="grow"><h3>Runtime + профиль GPIO</h3>
            <div className="form-grid"><label className="field"><span>SSID</span><input value={ssid} onChange={(e) => setSsid(e.target.value)} /></label><label className="field"><span>Wi‑Fi пароль</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label></div>
            <label className="field"><span>API token</span><div className="input-action"><input value={token} onChange={(e) => setToken(e.target.value)} /><button className="secondary" onClick={generateToken}>Сгенерировать</button></div></label>
            <button disabled={busy || token.length < 8 || !profileId} onClick={() => { if (requirePort()) runJob(() => api.startInstall(port, profileId, ssid, password, token)) }}>Установить runtime</button>
          </div>
        </div>
        <div className="step-card"><span className="step-num">03</span><div><h3>Проверка</h3><button className="secondary" disabled={busy} onClick={() => { if (requirePort()) runJob(() => api.startSerialFiles(port)) }}>Файлы через mpremote</button></div></div>
      </div>

      <div className="panel log-panel wide-log"><div className="panel-title"><div><p className="eyebrow">TOOL OUTPUT</p><h2>Диагностика</h2></div><button className="ghost secondary" onClick={() => setJob(null)}>Очистить</button></div><pre>{job?.log || 'Здесь появится живой вывод esptool / mpremote. Проценты не имитируются таймером: Studio показывает только то, что реально можно измерить.'}</pre></div>
    </section>
  )
}

function HistoryGitTab({ notify, initialPath = '', hostInfo = null }) {
  const [pathFilter, setPathFilter] = useState(initialPath || '')
  const [revisions, setRevisions] = useState([])
  const [selected, setSelected] = useState(null)
  const [diff, setDiff] = useState('')
  const [provider, setProvider] = useState('github')
  const [cloudToken, setCloudToken] = useState('')
  const [remember, setRemember] = useState(false)
  const [stored, setStored] = useState(false)
  const [account, setAccount] = useState(null)
  const [repoName, setRepoName] = useState('ghost32-project')
  const [privateRepo, setPrivateRepo] = useState(true)
  const [commitMessage, setCommitMessage] = useState('Update ESP32 snapshot')
  const [snapshotMessage, setSnapshotMessage] = useState('Manual project snapshot')
  const [cloudResult, setCloudResult] = useState(null)
  const [publishScope, setPublishScope] = useState('full')
  const [scanReport, setScanReport] = useState(null)
  const { job, busy, runJob } = useJobRunner(notify)
  const vaultName = hostInfo?.tools?.credential_vault || 'Credential vault'
  const persistentVault = !vaultName.startsWith('Session only')

  useEffect(() => { setPathFilter(initialPath || '') }, [initialPath])

  const loadHistory = async () => {
    try {
      const data = await api.history(pathFilter, 150)
      setRevisions(data.revisions || [])
    } catch (error) { notify(error.message, 'error') }
  }
  useEffect(() => { loadHistory() }, [pathFilter])
  useEffect(() => {
    setAccount(null); setCloudToken('')
    api.cloudTokenStatus(provider).then((data) => setStored(Boolean(data.stored))).catch(() => setStored(false))
  }, [provider])

  const inspect = async (revision) => {
    setSelected(revision)
    try {
      const data = await api.revisionDiff(revision.id)
      setDiff(data.diff || 'Нет отличий.')
    } catch (error) { setDiff(error.message) }
  }

  const testToken = async () => {
    const info = await runJob(() => api.startCloudAuth(provider, cloudToken, remember))
    if (info) { setAccount(info); setStored(Boolean(info.stored)) }
  }

  const scanSecrets = async () => {
    const report = await runJob(() => api.startCloudScan(publishScope))
    if (report) {
      setScanReport(report)
      notify(`Secret Scrubber: ${report.scrubber?.redactions || 0} redactions, ${report.skipped_count || 0} excluded`, 'success')
    }
  }

  const publish = async () => {
    setCloudResult(null)
    await runJob(
      () => api.cloudPublish(provider, cloudToken, remember, repoName, privateRepo, commitMessage, publishScope),
      async (result) => { setCloudResult(result); setScanReport(result.security || null); if (remember) setStored(true) }
    )
  }

  return (
    <section className="history-cloud-layout">
      {job && <div className="panel history-job-wide"><JobProgress job={job} /></div>}
      <div className="panel history-panel">
        <div className="panel-title"><div><p className="eyebrow">LOCAL HISTORY</p><h2>Версии файлов</h2></div><div className="button-row"><button className="secondary" disabled={busy} onClick={async () => { const result = await runJob(() => api.startHistorySnapshot(snapshotMessage)); if (result) await loadHistory() }}>Snapshot</button><button className="secondary" onClick={loadHistory}>↻</button></div></div>
        <div className="history-toolbar"><label className="field"><span>Фильтр по пути</span><input placeholder="/main.py или пусто = все" value={pathFilter} onChange={(e) => setPathFilter(e.target.value)} /></label><span className="revision-count">{revisions.length} rev</span></div>
        <label className="field compact snapshot-message"><span>Комментарий снимка проекта</span><input value={snapshotMessage} onChange={(e) => setSnapshotMessage(e.target.value)} /></label>
        <div className="revision-list">
          {revisions.length === 0 && <div className="empty-mini">История появится после первого сохранения файла через Wi‑Fi Code.</div>}
          {revisions.map((revision) => (
            <button key={revision.id} onClick={() => inspect(revision)} className={selected?.id === revision.id ? 'selected' : ''}>
              <span className={`revision-action ${revision.deleted ? 'deleted' : ''}`}>{revision.action}</span>
              <div><b>{revision.path}</b><small>#{revision.id} · {new Date(revision.created_at).toLocaleString()} · {revision.message || 'без комментария'}</small></div>
              <span className="revision-size">{revision.deleted ? 'DEL' : `${revision.bytes || 0} B`}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel diff-panel">
        <div className="panel-title"><div><p className="eyebrow">DIFF & ROLLBACK</p><h2>{selected ? `Revision #${selected.id}` : 'Выберите версию'}</h2></div>{selected && <button className="danger" onClick={async () => {
          if (!window.confirm(`Откатить ${selected.path} к revision #${selected.id}?`)) return
          const result = await runJob(() => api.startRestoreRevision(selected.id)); if (result) { await loadHistory(); await inspect(selected) }
        }}>Откатить</button>}</div>
        <pre className="diff-view">{diff || 'Здесь будет unified diff выбранной версии относительно текущего файла на ESP32.'}</pre>
        <div className="history-security"><b>Хранение:</b> SQLite в профиле текущего пользователя ОС. `config.json`, Wi‑Fi и credential-файлы исключены.</div>
      </div>

      <div className="panel cloud-panel">
        <div className="panel-title"><div><p className="eyebrow">CLOUD VERSIONING</p><h2>GitHub / GitLab</h2></div><span className={`vault-pill ${stored ? 'stored' : ''}`}>{stored ? 'TOKEN IN VAULT' : 'SESSION TOKEN'}</span></div>
        <div className="provider-switch"><button className={provider === 'github' ? 'active' : ''} onClick={() => setProvider('github')}>GitHub</button><button className={provider === 'gitlab' ? 'active' : ''} onClick={() => setProvider('gitlab')}>GitLab</button></div>
        <label className="field"><span>Personal access token {stored && '(можно оставить пустым)'}</span><input type="password" value={cloudToken} onChange={(e) => setCloudToken(e.target.value)} placeholder={stored ? `использовать ${vaultName}` : 'вставьте token'} /></label>
        <label className="check-row"><input type="checkbox" checked={remember} disabled={!persistentVault} onChange={(e) => setRemember(e.target.checked)} /><span>Запомнить token в {vaultName}</span></label>
        <div className="button-row"><button className="secondary" onClick={testToken}>Проверить token</button>{stored && <button className="ghost secondary" onClick={async () => { await api.cloudForget(provider); setStored(false); setAccount(null); notify(`Token удалён из ${vaultName}`) }}>Забыть</button>}</div>
        {account && <div className="account-card"><span>✓</span><div><b>{account.name}</b><small>@{account.username}</small></div></div>}

        <div className="cloud-divider" />
        <div className="publish-scope">
          <p className="eyebrow">PUBLISH SCOPE</p>
          <div className="provider-switch scope-switch">
            <button className={publishScope === 'device' ? 'active' : ''} onClick={() => { setPublishScope('device'); setScanReport(null) }}>ESP32 Project</button>
            <button className={publishScope === 'full' ? 'active' : ''} onClick={() => { setPublishScope('full'); setScanReport(null) }}>Full Studio Source</button>
          </div>
          <div className="scope-description">
            {publishScope === 'full' ? <>React source + собранный dist + FastAPI host + MicroPython runtime + firmware .bin + board profiles + Windows/Linux scripts + RU/EN docs + safe snapshot подключённой ESP32.</> : <>Только безопасные файлы проекта подключённой ESP32 + publish manifest.</>}
          </div>
        </div>
        <div className="form-grid"><label className="field"><span>Repository</span><input value={repoName} onChange={(e) => setRepoName(e.target.value)} /></label><label className="field"><span>Commit message</span><input value={commitMessage} onChange={(e) => setCommitMessage(e.target.value)} /></label></div>
        <label className="privacy-checkbox"><input type="checkbox" checked={privateRepo} onChange={(e) => setPrivateRepo(e.target.checked)} /><span><b>{privateRepo ? 'Private repository' : 'Public repository'}</b><small>{privateRepo ? 'виден только вам/участникам' : 'код будет доступен всем'}</small></span></label>
        <div className="secret-scrubber-card">
          <div className="secret-scrubber-head"><div><p className="eyebrow">SECRET SCRUBBER</p><b>Авто-обрезалка секретов · ON</b></div><button className="secondary" disabled={busy} onClick={scanSecrets}>{busy ? 'Сканирование…' : 'Проверить перед Git'}</button></div>
          <small>Блокирует credential/config-файлы и кэши; токены/пароли в текстовых файлах заменяет на &lt;REDACTED:...&gt;. Binary (например firmware .bin) публикуются, но их содержимое scrubber не анализирует.</small>
          {scanReport && <div className="scrub-report">
            <span><b>{scanReport.files}</b> файлов</span><span><b>{scanReport.scrubber?.files_redacted || 0}</b> изменено</span><span><b>{scanReport.scrubber?.redactions || 0}</b> redactions</span><span><b>{scanReport.scrubber?.binary_files || 0}</b> binary</span><span><b>{scanReport.skipped_count || 0}</b> исключено</span>
          </div>}
          {scanReport?.scrubber?.findings?.length > 0 && <div className="scrub-findings">{scanReport.scrubber.findings.slice(0, 4).map((finding, i) => <small key={`${finding.path}-${i}`}>{finding.path} · {finding.kind} · {finding.action}</small>)}</div>}
        </div>
        <div className="alert warn cloud-secret-note">В Git не попадут <b>config.json</b>, `.env`, ключи, базы, логи, `.venv`, `node_modules`, `dist` и скачанные firmware `.bin`. Full Studio Source содержит исходники React/FastAPI/MicroPython и обе документации.</div>
        <button className="publish-button" disabled={busy || !repoName.trim()} onClick={publish}>{busy ? 'Публикация…' : publishScope === 'full' ? 'Создать / опубликовать весь Studio Source' : 'Создать / опубликовать ESP32 Project'}</button>
        {cloudResult && <div className="publish-result"><b>✓ {cloudResult.repository}</b><small>{cloudResult.files} files · {cloudResult.branch} · {(cloudResult.commit || '').slice(0, 12)} · {cloudResult.scope === 'full' ? 'FULL SOURCE' : 'DEVICE'}</small><a href={cloudResult.url} target="_blank" rel="noreferrer">Открыть репозиторий ↗</a></div>}
      </div>
    </section>
  )
}


function ActivityTab({ notify }) {
  const [scope, setScope] = useState('all')
  const [kind, setKind] = useState('all')
  const [source, setSource] = useState('all')
  const [events, setEvents] = useState([])
  const [currentProject, setCurrentProject] = useState(null)
  const [selected, setSelected] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [loading, setLoading] = useState(false)

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await api.activity(scope, kind, source, 400)
      setEvents(data.events || [])
      setCurrentProject(data.current_project || null)
      if (selected) {
        const fresh = (data.events || []).find((item) => item.id === selected.id)
        if (fresh) setSelected(fresh)
      }
    } catch (error) {
      if (!silent) notify(error.message, 'error')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => { load() }, [scope, kind, source])
  useEffect(() => {
    if (!autoRefresh) return undefined
    const timer = window.setInterval(() => load(true), 2000)
    return () => window.clearInterval(timer)
  }, [autoRefresh, scope, kind, source])

  const sources = Array.from(new Set(events.map((item) => item.source).filter(Boolean))).sort()
  const errorCount = events.filter((item) => item.kind === 'error').length
  const actionCount = events.filter((item) => item.kind === 'action').length

  return (
    <section className="activity-layout">
      <div className="panel activity-main">
        <div className="panel-title">
          <div><p className="eyebrow">ACTION + ERROR LOG</p><h2>Журнал Studio</h2></div>
          <div className="button-row"><label className="check-row auto-refresh"><input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} /><span>live</span></label><button className="secondary" onClick={() => load()}>{loading ? '…' : '↻'}</button></div>
        </div>
        <div className="activity-summary">
          <div><span>PROJECT</span><b>{currentProject?.name || '—'}</b><small>{currentProject?.id || 'нет активного проекта'}</small></div>
          <div><span>ACTIONS</span><b>{actionCount}</b><small>в текущем фильтре</small></div>
          <div className={errorCount ? 'has-errors' : ''}><span>ERRORS</span><b>{errorCount}</b><small>{errorCount ? 'требуют внимания' : 'ошибок нет'}</small></div>
        </div>
        <div className="activity-filters">
          <div className="segmented"><button className={scope === 'all' ? 'active' : ''} onClick={() => setScope('all')}>Все проекты</button><button className={scope === 'current' ? 'active' : ''} onClick={() => setScope('current')}>Текущий проект</button></div>
          <div className="segmented"><button className={kind === 'all' ? 'active' : ''} onClick={() => setKind('all')}>Все</button><button className={kind === 'action' ? 'active' : ''} onClick={() => setKind('action')}>Действия</button><button className={kind === 'error' ? 'active error-filter' : 'error-filter'} onClick={() => setKind('error')}>Ошибки</button></div>
          <label className="field compact activity-source"><span>Подсистема</span><select value={source} onChange={(e) => setSource(e.target.value)}><option value="all">Все</option>{sources.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <button className="ghost danger" onClick={async () => {
            if (!window.confirm(`Очистить ${kind === 'error' ? 'ошибки' : kind === 'action' ? 'действия' : 'журнал'} (${scope === 'current' ? 'текущий проект' : 'все проекты'})?`)) return
            try { const result = await api.clearActivity(scope, kind); notify(`Удалено записей: ${result.deleted}`); setSelected(null); await load() } catch (error) { notify(error.message, 'error') }
          }}>Очистить</button>
        </div>
        <div className="activity-table-head"><span>Время</span><span>Тип</span><span>Подсистема / действие</span><span>Проект</span><span>Цель / job</span></div>
        <div className="activity-list">
          {events.length === 0 && <div className="empty-mini">Записей пока нет. Здесь появятся прошивки, GPIO-команды, сохранения файлов, публикации и ошибки.</div>}
          {events.map((event) => (
            <button key={event.id} className={`activity-row ${event.kind} ${selected?.id === event.id ? 'selected' : ''}`} onClick={() => setSelected(event)}>
              <span className="activity-time">{new Date(event.created_at).toLocaleString()}</span>
              <span className={`event-kind ${event.kind}`}>{event.kind === 'error' ? 'ERROR' : event.status === 'running' ? 'RUN' : 'ACTION'}</span>
              <span className="activity-action"><b>{event.source} · {event.action}</b><small>{event.message}</small></span>
              <span className="activity-project"><b>{event.project_name || 'Local Studio'}</b><small>{event.project_id || '—'}</small></span>
              <span className="activity-target"><b>{event.target || '—'}</b><small>{event.job_id ? `job ${event.job_id.slice(0, 8)}` : `#${event.id}`}</small></span>
            </button>
          ))}
        </div>
      </div>

      <aside className="panel activity-detail">
        <div className="panel-title"><div><p className="eyebrow">EVENT DETAILS</p><h2>{selected ? `#${selected.id}` : 'Выберите запись'}</h2></div></div>
        {!selected ? <div className="empty-mini">Ошибку можно открыть и сразу увидеть, к какому проекту, файлу, GPIO, COM-порту или cloud job она относится.</div> : <>
          <div className={`event-detail-status ${selected.kind}`}><b>{selected.kind === 'error' ? 'ОШИБКА' : selected.status?.toUpperCase()}</b><span>{selected.source}</span></div>
          <dl className="event-meta">
            <div><dt>Проект</dt><dd>{selected.project_name || 'Local Studio'}<small>{selected.project_id || '—'}</small></dd></div>
            <div><dt>Действие</dt><dd>{selected.action}</dd></div>
            <div><dt>Цель</dt><dd>{selected.target || '—'}</dd></div>
            <div><dt>Job</dt><dd>{selected.job_id || '—'}</dd></div>
            <div><dt>Время</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div>
          </dl>
          <div className="event-message"><b>Сообщение</b><p>{selected.message}</p></div>
          <div className="event-message"><b>Контекст</b><pre>{JSON.stringify(selected.context || {}, null, 2)}</pre></div>
          {selected.detail && <div className="event-message"><b>Хвост лога</b><pre>{selected.detail}</pre></div>}
        </>}
      </aside>
    </section>
  )
}

const PREVIEW_PROFILES = [
  { id: 'esp32-c3-supermini', name: 'ESP32-C3 SuperMini', family: 'ESP32-C3', chip: 'esp32c3', verified: true, memory: { flash_mb: 4, psram_mb: 0 }, description: 'Компактный C3 SuperMini: GPIO0..10, 20, 21.', pins: Array(13).fill({ available: true }) },
  { id: 'esp32-s3-supermini', name: 'ESP32-S3 Super Mini (N4R2 common)', family: 'ESP32-S3', chip: 'esp32s3', verified: false, memory: { flash_mb: 4, psram_mb: 2, psram_mode: 'quad' }, description: 'Native USB, компактный S3 Super Mini; pinout клона проверяется по маркировке.', pins: Array(32).fill({ available: true }) },
  { id: 'esp32-s3-uno-generic', name: 'ESP32-S3 UNO / UNO-style (generic)', family: 'ESP32-S3', chip: 'esp32s3', verified: false, memory: { flash_mb: 0, psram_mb: 0, psram_mode: 'auto' }, description: 'Консервативный UNO-style профиль.', pins: [...Array(34).fill({ available: true }), ...Array(3).fill({ available: false })] },
  { id: 'esp32-s3-uno-n16r8', name: 'ESP32-S3 UNO N16R8', family: 'ESP32-S3', chip: 'esp32s3', verified: false, memory: { flash_mb: 16, psram_mb: 8, psram_mode: 'octal' }, description: 'UNO-формат, 16MB Flash + 8MB Octal PSRAM.', pins: [...Array(34).fill({ available: true }), ...Array(3).fill({ available: false })] },
  { id: 'esp32-s3-devkitc1-n16r8', name: 'ESP32-S3-DevKitC-1 N16R8', family: 'ESP32-S3', chip: 'esp32s3', verified: true, memory: { flash_mb: 16, psram_mb: 8, psram_mode: 'octal' }, description: 'DevKitC-1 header layout + WROOM-1 N16R8.', pins: [...Array(32).fill({ available: true }), ...Array(3).fill({ available: false })] },
  { id: 'esp32-s3-generic', name: 'ESP32-S3 Generic / Custom base', family: 'ESP32-S3', chip: 'esp32s3', verified: false, memory: { flash_mb: 4, psram_mb: 0, psram_mode: 'auto' }, description: 'Базовый профиль для других S3 плат.', pins: Array(38).fill({ available: true }) }
]

export default function App() {
  const preview = new URLSearchParams(window.location.search).has('preview')
  const [tab, setTab] = useState(preview ? 'usb' : 'gpio')
  const [historyPath, setHistoryPath] = useState('')
  const [baseUrl, setBaseUrl] = useState('http://192.168.4.1')
  const [token, setToken] = useState('')
  const [connected, setConnected] = useState(false)
  const [status, setStatus] = useState(null)
  const [deviceInfo, setDeviceInfo] = useState(null)
  const [hostInfo, setHostInfo] = useState(null)
  const [profiles, setProfiles] = useState(preview ? PREVIEW_PROFILES : [])
  const [toast, setToast] = useState(null)

  const notify = (message, type = 'ok') => {
    setToast({ message, type })
    window.setTimeout(() => setToast(null), 4200)
  }

  const connectionRunner = useJobRunner(notify)

  const refresh = async (silent = false) => {
    try {
      const data = await api.status(); setStatus(data); setConnected(true); return data
    } catch (error) {
      setConnected(false); if (!silent) notify(error.message, 'error'); throw error
    }
  }

  const connect = async () => {
    const result = await connectionRunner.runJob(() => api.startConnect(baseUrl, token))
    if (!result) { setConnected(false); return }
    setDeviceInfo(result.info || null)
    setStatus(result.status || null)
    setConnected(true)
  }

  useEffect(() => {
    if (preview) return
    api.hostInfo().then(setHostInfo).catch(() => {})
    api.boards().then((data) => setProfiles(data.profiles || [])).catch((error) => notify(error.message, 'error'))
  }, [])

  useEffect(() => {
    if (!connected || preview) return undefined
    const timer = window.setInterval(() => refresh(true).catch(() => {}), 1800)
    return () => window.clearInterval(timer)
  }, [connected, preview])

  const wifi = status?.wifi || {}
  const memKb = status?.free_memory ? `${Math.round(status.free_memory / 1024)} KB` : '—'
  const uptime = status?.uptime_ms ? `${Math.floor(status.uptime_ms / 1000)} s` : '—'
  const boardName = deviceInfo?.board || '—'
  const memProfile = deviceInfo?.memory_profile || {}
  const connectionSub = useMemo(() => connected ? `${wifi.mode || ''} · ${wifi.ssid || ''}` : 'не подключено', [connected, wifi.mode, wifi.ssid])
  const openHistory = (path = '') => { setHistoryPath(path); setTab('history') }

  return (
    <div className="app-shell">
      <Toast toast={toast} onClose={() => setToast(null)} />
      <header className="topbar">
        <div className="brand"><div className="chip-logo"><span>ESP</span><b>32</b></div><div><strong>MultiBoard Studio</strong><span>React · FastAPI · MicroPython</span></div></div>
        <div className="topbar-right"><span className="version-pill">v2.5.0</span><div className={`status-pill ${connected ? 'online' : ''}`}><i />{connected ? 'DEVICE ONLINE' : 'LOCAL STUDIO'}</div></div>
      </header>

      <main>
        <section className="hero panel">
          <div className="hero-copy"><p className="eyebrow">MULTI-BOARD CONTROL SURFACE</p><h1>ESP32 Studio: код, GPIO, прошивка и версии</h1><p>Stage Progress, Local History, Full Studio Source в GitHub/GitLab, Secret Scrubber и Action/Error Logs с привязкой к проекту.</p>
            <div className="hero-board-row">{profiles.slice(0, 4).map((p) => <span key={p.id}>{p.name.replace('ESP32-', '')}</span>)}<span>LOCAL HISTORY</span><span>GITHUB / GITLAB</span><span>ACTION / ERROR LOG</span></div>
          </div>
          <div className="connect-box"><label className="field"><span>ESP32 URL / IP</span><input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} /></label><label className="field"><span>API token</span><input type="password" value={token} onChange={(e) => setToken(e.target.value)} /></label><button disabled={connectionRunner.busy || preview} onClick={connect}>{preview ? 'Preview mode' : connectionRunner.busy ? 'Подключение…' : 'Подключить по Wi‑Fi'}</button><JobProgress job={connectionRunner.job} compact /></div>
        </section>

        <section className="metrics-grid">
          <Metric label="BOARD" value={boardName} sub={deviceInfo?.chip ? `${deviceInfo.chip} · MicroPython ${deviceInfo.micropython || ''}` : `${profiles.length} board profiles`} />
          <Metric label="NETWORK" value={wifi.ip || '—'} sub={connectionSub} />
          <Metric label="MEMORY" value={memProfile.flash_mb ? `${memProfile.flash_mb}MB Flash` : memKb} sub={memProfile.psram_mb ? `${memProfile.psram_mb}MB ${memProfile.psram_mode} PSRAM` : 'runtime / profile'} />
          <Metric label="HOST" value={hostInfo?.python ? `Python ${hostInfo.python}` : 'Windows / Linux'} sub={connected ? `uptime ${uptime}` : hostInfo?.tools ? `esptool ${hostInfo.tools.esptool} · mpremote ${hostInfo.tools.mpremote}` : 'uv + Python 3.13'} />
        </section>

        <nav className="tabs"><button className={tab === 'gpio' ? 'active' : ''} onClick={() => setTab('gpio')}>GPIO Matrix</button><button className={tab === 'files' ? 'active' : ''} onClick={() => setTab('files')}>Wi‑Fi Code</button><button className={tab === 'usb' ? 'active' : ''} onClick={() => setTab('usb')}>USB & Board</button><button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>Versions & Git</button><button className={tab === 'activity' ? 'active' : ''} onClick={() => setTab('activity')}>Logs</button></nav>

        {!connected && !['usb', 'activity'].includes(tab) && !preview ? (
          <section className="empty panel"><div className="signal">⌁</div><h2>Подключите контроллер</h2><p>Для GPIO, Wi‑Fi файлов, Local History и Cloud snapshot нужно сначала подключиться к ESP32. Прошивка доступна в USB & Board.</p><button className="secondary" onClick={() => setTab('usb')}>Открыть USB & Board</button></section>
        ) : (
          <>
            {tab === 'gpio' && <GpioTab status={status} deviceInfo={deviceInfo} refresh={() => refresh(false)} notify={notify} />}
            {tab === 'files' && <FilesTab notify={notify} openHistory={openHistory} />}
            {tab === 'usb' && <UsbBoardTab notify={notify} profiles={profiles} />}
            {tab === 'history' && <HistoryGitTab notify={notify} initialPath={historyPath} hostInfo={hostInfo} />}
            {tab === 'activity' && <ActivityTab notify={notify} />}
          </>
        )}
      </main>
      <footer><span>ESP32 MultiBoard Studio 2.5.0</span><span>Real progress · Local History · Full Git publish · Secret Scrubber · Action/Error Logs</span></footer>
    </div>
  )
}

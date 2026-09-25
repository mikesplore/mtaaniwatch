import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import './App.css'

type Report = {
  id: number; reference: string; category: string; area: string | null; landmark: string | null
  impact_reported: string[]; summary: string; language: string | null; source: string
  verified: boolean; is_demo: boolean; created_at: string
}
type TaskStatus = 'reported' | 'assigned' | 'in_progress' | 'resolved' | 'cancelled'
type Task = { id: number; report_id: number; crew_name: string | null; status: TaskStatus; updated_at: string; history: { status: TaskStatus; note: string | null; created_at: string }[] }
type Crew = { id: number; name: string; home_area_id: number | null; is_demo: boolean }
type Cluster = { id: number; category: string; area_name: string; status: 'suggested' | 'accepted' | 'dismissed'; review_note: string | null; created_at: string; reports: Pick<Report, 'id' | 'reference' | 'area' | 'landmark' | 'summary' | 'verified' | 'is_demo' | 'created_at'>[] }
type Section = 'overview' | 'reports' | 'tasks' | 'clusters'

const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options?.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

const statusLabel: Record<TaskStatus, string> = { reported: 'Reported', assigned: 'Assigned', in_progress: 'In progress', resolved: 'Resolved', cancelled: 'Cancelled' }
const categoryLabel = (category: string) => category.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
const timeAgo = (value: string) => {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    report: <><path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8z"/><path d="M8 3v5h5M8 13h8M8 17h8"/></>,
    task: <><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M7 2v4m10-4v4M3 10h18M8 15l2 2 5-5"/></>,
    cluster: <><circle cx="12" cy="12" r="3"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><path d="m7 7 3 3m7-3-3 3m-7 7 3-3m7 3-3-3"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.6 9a7 7 0 0 1 11.6-2L20 12M4 12l2.8 5a7 7 0 0 0 11.6-2"/></>,
    pin: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
    arrow: <><path d="M5 12h14m-7-7 7 7-7 7"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
  }
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function App() {
  const [reports, setReports] = useState<Report[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [crews, setCrews] = useState<Crew[]>([])
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [section, setSection] = useState<Section>('overview')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [areaFilter, setAreaFilter] = useState('all')
  const [taskQuery, setTaskQuery] = useState('')
  const [taskFilter, setTaskFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState<number | null>(null)
  const [selectedReport, setSelectedReport] = useState<Report | null>(null)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null)

  const loadData = useCallback(async () => {
    setError('')
    try {
      const [nextReports, nextTasks, nextCrews, nextClusters] = await Promise.all([
        api<Report[]>('/reports'), api<Task[]>('/tasks'), api<Crew[]>('/crews'), api<Cluster[]>('/clusters'),
      ])
      setReports(nextReports); setTasks(nextTasks); setCrews(nextCrews); setClusters(nextClusters)
      setFetchedAt(new Date())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not connect to the MtaaniWatch API.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const initialLoad = window.setTimeout(() => { void loadData() }, 0)
    const interval = window.setInterval(() => { void loadData() }, 30_000)
    return () => { window.clearTimeout(initialLoad); window.clearInterval(interval) }
  }, [loadData])

  const taskByReport = useMemo(() => new Map(tasks.map((task) => [task.report_id, task])), [tasks])
  const reportsWithoutTasks = reports.filter((report) => !taskByReport.has(report.id))
  const activeTasks = tasks.filter((task) => !['resolved', 'cancelled'].includes(task.status))
  const stats = [
    { label: 'All reports', value: reports.length, detail: `${reports.filter((report) => !report.verified).length} awaiting review`, icon: 'report', tone: 'blue' },
    { label: 'Needs assignment', value: tasks.filter((task) => task.status === 'reported').length, detail: 'Ready for a crew', icon: 'task', tone: 'amber' },
    { label: 'In progress', value: tasks.filter((task) => task.status === 'in_progress').length, detail: 'Field response underway', icon: 'arrow', tone: 'violet' },
    { label: 'Resolved', value: tasks.filter((task) => task.status === 'resolved').length, detail: 'Reports closed', icon: 'check', tone: 'green' },
  ]

  const filteredReports = reports.filter((report) => {
    const task = taskByReport.get(report.id)
    const matchesQuery = `${report.reference} ${report.area ?? ''} ${report.landmark ?? ''} ${report.summary}`.toLowerCase().includes(query.toLowerCase())
    const matchesStatus = filter === 'all' || task?.status === filter
    const matchesArea = areaFilter === 'all' || report.area === areaFilter
    return matchesQuery && matchesStatus && matchesArea
  })
  const filteredTasks = tasks.filter((task) => {
    const report = reports.find((item) => item.id === task.report_id)
    const matchesQuery = `${report?.reference ?? ''} ${report?.area ?? ''} ${report?.landmark ?? ''} ${report?.summary ?? ''} ${task.crew_name ?? ''}`.toLowerCase().includes(taskQuery.toLowerCase())
    return matchesQuery && (taskFilter === 'all' || task.status === taskFilter)
  })
  const areas = [...new Set(reports.map((report) => report.area).filter((area): area is string => Boolean(area)))].sort()

  const mutate = async (taskId: number, action: () => Promise<unknown>, success: string) => {
    setBusy(taskId); setNotice('')
    try { await action(); await loadData(); setNotice(success) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Action failed.') }
    finally { setBusy(null) }
  }

  const assignCrew = (task: Task, crewName: string) => mutate(task.id,
    () => api(`/tasks/${task.id}/assign`, { method: 'POST', body: JSON.stringify({ crew_name: crewName }) }), 'Crew assigned.')
  const advanceTask = (task: Task) => {
    const next: Partial<Record<TaskStatus, TaskStatus>> = { assigned: 'in_progress', in_progress: 'resolved' }
    const status = next[task.status]
    if (!status) return
    void mutate(task.id, () => api(`/tasks/${task.id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }), `Task marked ${statusLabel[status].toLowerCase()}.`)
  }
  const suggestClusters = async () => {
    setBusy(-1); setNotice(''); setError('')
    try { const result = await api<{ created: number }>('/clusters/suggest', { method: 'POST' }); await loadData(); setNotice(`${result.created} possible cluster${result.created === 1 ? '' : 's'} added for review.`) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not find clusters.') }
    finally { setBusy(null) }
  }
  const reviewCluster = (cluster: Cluster, status: 'accepted' | 'dismissed') => mutate(cluster.id,
    () => api(`/clusters/${cluster.id}`, { method: 'PATCH', body: JSON.stringify({ status, note: null }) }), `Cluster ${status}.`)
  const verifyReport = async (report: Report) => {
    setBusy(report.id); setError('')
    try {
      const updated = await api<Report>(`/reports/${report.reference}/verification`, { method: 'PATCH', body: JSON.stringify({ verified: true }) })
      setReports((current) => current.map((item) => item.id === updated.id ? updated : item))
      setSelectedReport(updated)
      setNotice(`${report.reference} marked as verified.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not verify report.') }
    finally { setBusy(null) }
  }
  const createReportTask = async (report: Report) => {
    setBusy(report.id); setError(''); setNotice('')
    try {
      await api(`/reports/${report.reference}/task`, { method: 'POST' })
      await loadData()
      setNotice(`Response task created for ${report.reference}.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not create response task.') }
    finally { setBusy(null) }
  }
  const backfillReportTasks = async () => {
    setBusy(-2); setError(''); setNotice('')
    try {
      const result = await api<{ created: number }>('/tasks/backfill', { method: 'POST' })
      await loadData()
      setNotice(`${result.created} response task${result.created === 1 ? '' : 's'} created.`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not recover response tasks.') }
    finally { setBusy(null) }
  }

  const pageTitle = section === 'overview' ? 'Operations overview' : section === 'reports' ? 'Reports' : section === 'tasks' ? 'Response tasks' : 'Possible clusters'

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#overview" onClick={() => setSection('overview')}><span className="brand-mark">m<span>.</span></span><span className="brand-copy"><strong>mtaaniwatch</strong><small>RESPONSE CONSOLE</small></span></a>
      <div className="nav-label">WORKSPACE</div>
      <nav className="main-nav" aria-label="Main navigation">
        {([['overview', 'grid', 'Overview'], ['reports', 'report', 'Reports'], ['tasks', 'task', 'Tasks'], ['clusters', 'cluster', 'Clusters']] as [Section, string, string][]).map(([id, icon, label]) =>
          <button key={id} className={`nav-item ${section === id ? 'selected' : ''}`} onClick={() => setSection(id)}><Icon name={icon}/><span>{label}</span>{id === 'reports' && <b>{reports.length}</b>}{id === 'tasks' && <b>{activeTasks.length}</b>}{id === 'clusters' && clusters.some((cluster) => cluster.status === 'suggested') && <i className="nav-dot"/>}</button>)}
      </nav>
      <div className="sidebar-bottom"><div className="profile"><div className="avatar">MO</div><div><strong>Operations Admin</strong><small>Mombasa County</small></div><span className="profile-more">···</span></div></div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{pageTitle}</strong></div><div className="topbar-actions"><span className="connection" title={fetchedAt ? `Last updated ${fetchedAt.toLocaleTimeString()}` : 'Waiting for API'}><i className={error ? 'offline-dot' : 'online-dot'}/>{error ? 'API unavailable' : fetchedAt ? `Updated ${fetchedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Connecting'}</span><button className="icon-button" aria-label="Refresh data" onClick={() => { setLoading(true); void loadData() }} disabled={loading}><Icon name="refresh"/></button><div className="top-avatar">MO</div></div></header>
      <div className="content-wrap">
        {error && <div className="alert alert-error"><span>!</span><div><strong>Unable to load dashboard data</strong><small>{error}. Confirm FastAPI is running at localhost:8000.</small></div><button onClick={() => { setLoading(true); void loadData() }}>Retry</button></div>}
        {notice && <div className="alert alert-success"><span>✓</span>{notice}<button aria-label="Dismiss" onClick={() => setNotice('')}>×</button></div>}

        {(section === 'overview' || section === 'reports') && <>
          {section === 'overview' && <>
            <div className="stats-grid">{stats.map((stat) => <article className="stat-card" key={stat.label}><div className={`stat-icon ${stat.tone}`}><Icon name={stat.icon}/></div><span className="stat-label">{stat.label}</span><div className="stat-value">{loading ? '—' : stat.value}</div><div className="stat-detail">{stat.detail}</div></article>)}</div>
            <div className="section-head"><div><h2>Recent reports</h2><p>Latest community-submitted incidents</p></div><button className="text-button" onClick={() => setSection('reports')}>View all <Icon name="arrow" size={16}/></button></div>
          </>}
          <section className="panel report-panel">
            <div className="table-toolbar"><label className="search-box"><Icon name="search" size={17}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search reports, areas, landmarks..."/></label><div className="toolbar-controls"><select value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter by status"><option value="all">All statuses</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={areaFilter} onChange={(event) => setAreaFilter(event.target.value)} aria-label="Filter by area"><option value="all">All areas</option>{areas.map((area) => <option key={area} value={area}>{area}</option>)}</select><button className="button button-filter" onClick={() => { setQuery(''); setFilter('all'); setAreaFilter('all') }}>Clear</button></div></div>
            <div className="table-scroll"><table><thead><tr><th>REPORT</th><th>LOCATION</th><th>ISSUE SUMMARY</th><th>STATUS</th><th>RECEIVED</th><th/></tr></thead><tbody>
              {filteredReports.slice(0, section === 'overview' ? 6 : undefined).map((report) => { const task = taskByReport.get(report.id); return <tr key={report.id}>
                <td><div className="reference-cell"><span className="report-symbol"><Icon name="report" size={16}/></span><div><strong>{report.reference}</strong><small>{categoryLabel(report.category)}</small></div></div></td>
                <td><div className="location-cell"><strong>{report.area || 'Area unknown'}</strong><small><Icon name="pin" size={13}/>{report.landmark || 'No landmark provided'}</small></div></td>
                <td><div className="summary-cell">{report.summary}<div className="source-meta"><span>{report.source.replaceAll('_', ' ')}</span><span>·</span><span>{report.language?.toUpperCase() || '—'}</span>{!report.verified && <span className="unverified-tag">Unverified</span>}</div></div></td>
                <td><StatusBadge status={task?.status || 'reported'}/></td><td className="time-cell" title={new Date(report.created_at).toLocaleString()}>{timeAgo(report.created_at)}</td><td><button className="row-open" onClick={() => setSelectedReport(report)}>Details</button></td>
              </tr> })}
              {!loading && filteredReports.length === 0 && <tr><td colSpan={6}><div className="empty-state"><span>⌕</span><strong>No reports found</strong><small>Try changing your search or filters.</small></div></td></tr>}
              {loading && <tr><td colSpan={6}><div className="loading-state">Loading reports…</div></td></tr>}
            </tbody></table></div>
            {filteredReports.length > 6 && section === 'overview' && <button className="table-footer" onClick={() => setSection('reports')}>View all {filteredReports.length} reports <Icon name="arrow" size={15}/></button>}
          </section>
          {section === 'overview' && <div className="bottom-grid"><section className="panel activity-panel"><div className="panel-title"><div><h2>Response activity</h2><p>Latest task status updates</p></div><button className="text-button" onClick={() => setSection('tasks')}>All tasks <Icon name="arrow" size={15}/></button></div><div className="activity-list">{tasks.slice(0, 4).map((task) => { const report = reports.find((item) => item.id === task.report_id); const event = task.history.at(-1); return <div className="activity-item" key={task.id}><span className={`activity-dot ${task.status}`}/><div><strong>{task.crew_name || 'Awaiting crew'} <span>{statusLabel[task.status].toLowerCase()}</span></strong><small>{report?.reference || 'Report'} · {event?.note || statusLabel[task.status]}</small></div><time>{timeAgo(event?.created_at || task.updated_at)}</time></div> })}{!loading && tasks.length === 0 && <div className="empty-inline">No response activity yet.</div>}</div></section><section className="panel cluster-callout"><div className="cluster-art"><span/><span/><span/><span/><Icon name="cluster" size={25}/></div><div><span className="eyebrow">PATTERN REVIEW</span><h2>Spot reports that may be connected</h2><p>Review reports sharing an area and issue type. Clusters are suggestions until you confirm them.</p><button className="button button-dark" onClick={() => { setSection('clusters'); void suggestClusters() }} disabled={busy === -1}>Find possible clusters <Icon name="arrow" size={15}/></button></div></section></div>}
        </>}

        {section === 'tasks' && <section className="panel tasks-panel"><div className="panel-title task-title"><div><p>Assign crews and track response progress</p>{reportsWithoutTasks.length > 0 && <small>{reportsWithoutTasks.length} reports need response tasks.</small>}</div><div className="toolbar-controls"><span className="count-pill">{tasks.length} total</span>{reportsWithoutTasks.length > 0 && <button className="button button-primary" onClick={() => void backfillReportTasks()} disabled={busy === -2}>{busy === -2 ? 'Creating…' : `Create ${reportsWithoutTasks.length} missing task${reportsWithoutTasks.length === 1 ? '' : 's'}`}</button>}</div></div><div className="table-toolbar task-toolbar"><label className="search-box"><Icon name="search" size={17}/><input value={taskQuery} onChange={(event) => setTaskQuery(event.target.value)} placeholder="Search tasks, areas, crews..."/></label><div className="toolbar-controls"><select value={taskFilter} onChange={(event) => setTaskFilter(event.target.value)} aria-label="Filter tasks by status"><option value="all">All task statuses</option>{Object.entries(statusLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button className="button button-filter" onClick={() => { setTaskQuery(''); setTaskFilter('all') }}>Clear</button></div></div><div className="task-list">{filteredTasks.map((task) => { const report = reports.find((item) => item.id === task.report_id); return <article className="task-card" key={task.id}><div className="task-leading"><span className={`task-status-icon ${task.status}`}><Icon name={task.status === 'resolved' ? 'check' : 'task'} size={17}/></span><div className="task-main"><div className="task-refline"><button className="link-button" onClick={() => report && setSelectedReport(report)}>{report?.reference || `Task #${task.id}`}</button><StatusBadge status={task.status}/></div><h3>{report?.summary || 'Report details unavailable'}</h3><p><Icon name="pin" size={14}/>{report?.area || 'Area unknown'}{report?.landmark ? ` · ${report.landmark}` : ''}</p></div></div><div className="task-actions">{task.status === 'reported' ? <select defaultValue="" aria-label={`Assign crew to ${report?.reference}`} onChange={(event) => { if (event.target.value) void assignCrew(task, event.target.value) }} disabled={busy === task.id}><option value="">Assign a crew</option>{crews.map((crew) => <option key={crew.id} value={crew.name}>{crew.name}</option>)}</select> : task.status === 'assigned' || task.status === 'in_progress' ? <button className="button button-primary" onClick={() => advanceTask(task)} disabled={busy === task.id}>{busy === task.id ? 'Saving…' : task.status === 'assigned' ? 'Start response' : 'Mark resolved'}<Icon name="arrow" size={15}/></button> : <span className="task-crew">{task.crew_name || 'No crew assigned'}</span>}</div><div className="task-footer"><span>{task.crew_name ? `Assigned to ${task.crew_name}` : 'Unassigned'}</span><span>Updated {timeAgo(task.updated_at)}</span></div></article> })}{!loading && filteredTasks.length === 0 && <div className="empty-state"><strong>{tasks.length ? 'No matching tasks' : 'No tasks yet'}</strong><small>{tasks.length ? 'Try changing the search or status filter.' : 'Tasks appear when reports are received.'}</small></div>}</div></section>}

        {section === 'clusters' && <><div className="cluster-page-intro"><p>Related reports grouped by issue type and area for coordinator review.</p><button className="button button-primary" onClick={() => void suggestClusters()} disabled={busy === -1}>{busy === -1 ? 'Finding…' : <><Icon name="cluster" size={16}/> Find possible clusters</>}</button></div><div className="cluster-list">{clusters.map((cluster) => <article className="panel cluster-card" key={cluster.id}><div className="cluster-card-head"><div><span className="cluster-chip"><Icon name="cluster" size={14}/>{categoryLabel(cluster.category)}</span><h2>{cluster.area_name}</h2><p>{cluster.reports.length} related reports · created {timeAgo(cluster.created_at)}</p></div><span className={`review-badge ${cluster.status}`}>{cluster.status}</span></div><div className="cluster-reports">{cluster.reports.map((report) => <div className="cluster-report" key={report.id}><strong>{report.reference}</strong><span>{report.summary}</span></div>)}</div>{cluster.status === 'suggested' && <div className="cluster-actions"><span>Confirm that these reports describe the same incident.</span><div><button className="button button-filter" onClick={() => void reviewCluster(cluster, 'dismissed')} disabled={busy === cluster.id}>Dismiss</button><button className="button button-primary" onClick={() => void reviewCluster(cluster, 'accepted')} disabled={busy === cluster.id}><Icon name="check" size={15}/> Accept cluster</button></div></div>}{cluster.review_note && <p className="review-note">Coordinator note: {cluster.review_note}</p>}</article>)}{!loading && clusters.length === 0 && <div className="panel empty-state"><span><Icon name="cluster" size={25}/></span><strong>No clusters to review</strong><small>Find possible clusters to group active reports from the same area.</small></div>}</div></>}

        <footer className="page-footer"><span>◉ MtaaniWatch <i>·</i> Coordinator workspace</span><span>Reports remain unverified until confirmed</span></footer>
      </div>
    </main>
    {selectedReport && <ReportDetails report={selectedReport} task={taskByReport.get(selectedReport.id)} busy={busy === selectedReport.id} onVerify={() => void verifyReport(selectedReport)} onCreateTask={() => void createReportTask(selectedReport)} onClose={() => setSelectedReport(null)}/>}
  </div>
}

function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`status-badge ${status}`}><i/>{statusLabel[status]}</span>
}

function ReportDetails({ report, task, busy, onVerify, onCreateTask, onClose }: { report: Report; task?: Task; busy: boolean; onVerify: () => void; onCreateTask: () => void; onClose: () => void }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])
  return <div className="drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <aside className="report-drawer" role="dialog" aria-modal="true" aria-labelledby="report-drawer-title">
      <div className="drawer-top"><div><span className="eyebrow">REPORT DETAILS</span><h2 id="report-drawer-title">{report.reference}</h2></div><button className="drawer-close" onClick={onClose} aria-label="Close report details">×</button></div>
      <div className="drawer-scroll">
        <div className="drawer-badges"><StatusBadge status={task?.status || 'reported'}/><span className={`verification-badge ${report.verified ? 'verified' : 'unverified'}`}>{report.verified ? 'Verified' : 'Needs review'}</span></div>
        <section className="drawer-section"><h3>What was reported</h3><p className="drawer-summary">{report.summary}</p>{report.impact_reported.length > 0 && <><h4>Reported impact</h4><ul className="impact-list">{report.impact_reported.map((impact, index) => <li key={`${impact}-${index}`}>{impact}</li>)}</ul></>}</section>
        <section className="drawer-section"><h3>Location</h3><div className="drawer-location"><span className="drawer-pin"><Icon name="pin" size={17}/></span><div><strong>{report.area || 'Area not identified'}</strong><small>{report.landmark || 'No nearby landmark provided'}</small></div></div></section>
        <section className="drawer-section"><h3>Report information</h3><dl className="detail-grid"><div><dt>Category</dt><dd>{categoryLabel(report.category)}</dd></div><div><dt>Received via</dt><dd>{report.source.replaceAll('_', ' ')}</dd></div><div><dt>Language</dt><dd>{report.language?.toUpperCase() || 'Not identified'}</dd></div><div><dt>Received</dt><dd>{new Date(report.created_at).toLocaleString()}</dd></div><div><dt>Assigned crew</dt><dd>{task?.crew_name || 'Unassigned'}</dd></div></dl></section>
        <section className="drawer-section"><h3>Response history</h3>{task?.history.length ? <div className="timeline">{task.history.map((event, index) => <div className="timeline-event" key={`${event.status}-${event.created_at}-${index}`}><span className={`timeline-node ${event.status}`}/><div><strong>{statusLabel[event.status]}</strong><small>{event.note || 'Status updated'}</small><time>{new Date(event.created_at).toLocaleString()}</time></div></div>)}</div> : <p className="no-history">No response history available.</p>}</section>
      </div>
      <div className="drawer-footer">{!task && <button className="button button-primary" onClick={onCreateTask} disabled={busy}>{busy ? 'Saving…' : <><Icon name="task" size={15}/> Create response task</>}</button>}{!report.verified && <button className="button button-primary" onClick={onVerify} disabled={busy}>{busy ? 'Saving…' : <><Icon name="check" size={15}/> Mark as verified</>}</button>}<button className="button button-filter" onClick={onClose}>Close</button></div>
    </aside>
  </div>
}

export default App

import { Link, NavLink, Route, Routes } from "react-router"

import { copy } from "./copy"
import Admin from "./routes/Admin"
import Catalog from "./routes/Catalog"
import Interstitial from "./routes/Interstitial"
import NotFound from "./routes/NotFound"
import { useStatus } from "./useStatus"

function announcement(
  s: ReturnType<typeof useStatus>["status"],
  projects: ReturnType<typeof useStatus>["projects"],
): string {
  if (!s) return ""
  const name = projects?.find((p) => p.id === s.active)?.name ?? s.active ?? ""
  if (s.me.role === "queued" && s.me.position !== null) return copy.announce.queued(s.me.position)
  if (!s.active) return copy.announce.idle
  if (s.status === "starting") return copy.announce.starting(name)
  if (s.status === "failed") return copy.announce.failed(name)
  return copy.announce.running(name)
}

export default function App() {
  const { status, projects } = useStatus()
  return (
    <>
      <a className="skip" href="#main">
        {copy.skipLink}
      </a>
      <header className="site-header">
        <Link to="/" className="brand">
          {copy.siteName}
        </Link>
        <nav aria-label="Primary">
          <NavLink to="/" end>
            {copy.nav.catalog}
          </NavLink>
          <NavLink to="/admin">{copy.nav.admin}</NavLink>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <div className="sr-only" role="status" aria-live="polite">
          {announcement(status, projects)}
        </div>
        <Routes>
          <Route path="/" element={<Catalog />} />
          <Route path="/p/:id" element={<Interstitial />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  )
}

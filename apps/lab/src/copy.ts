/** Every user-facing string lives here so the voice can be edited in one place. */

/** Lease durations come from /api/status, so the copy matches the server's config. */
interface LeaseTimes {
  window_s: number
  grace_s: number
  idle_s: number
}

const mins = (s: number): number => Math.max(1, Math.round(s / 60))
const minutes = (s: number): string => {
  const m = mins(s)
  return `${m} minute${m === 1 ? "" : "s"}`
}

const queueEstimate = (position: number, l: LeaseTimes): string =>
  `up to ~${position * (mins(l.window_s) + mins(l.grace_s))} min`

const idleRule = (l: LeaseTimes): string =>
  `If someone is waiting and the visitor whose turn it is stops interacting for about ${minutes(l.idle_s)}, the turn hands over early.`

const seconds = (n: number): string => `about ${n} seconds`

export const copy = {
  siteName: "The lab",
  skipLink: "Skip to content",
  nav: { catalog: "Projects", admin: "Owner" },
  tagline: (count: number | null): string =>
    `${count === null ? "Machine-learning projects" : count === 1 ? "1 machine-learning project" : `${count} machine-learning projects`}, one small server. Run one live, or watch the recorded demo.`,

  loading: "Loading the latest state of the box...",
  loadError:
    "Couldn't reach the control plane, so the status below may be stale. This page retries every few seconds on its own.",

  projectsFailed: {
    body: "Couldn't load the project list, so there is nothing to show yet, and the demo links come from that list too. This page keeps retrying on its own; you can also retry now.",
    retry: "Retry now",
  },

  catalog: {
    heading: "Projects you can run live",
    eta: (n: number) => `Boots in ${seconds(n)}`,
    runLive: "Run live",
    details: "Open",
    demo: "Watch the demo",
    emptyProjects: "No projects are published yet. Check back soon.",
  },

  box: {
    heading: "What the box is doing",
    idle: "Idle. Nothing is running, so you can start a project right now with no wait.",
    runningFor: (project: string, holder: string) => `${project} is running for ${holder}.`,
    youHold: "you",
    starting: (project: string) =>
      `${project} is starting. It counts as ready only once its health check passes.`,
    window: "Time left in the turn",
    grace: "Handing off to the next visitor in",
    queueHeading: "Queue",
    queueEmpty: "Nobody is waiting.",
    me: "(Me)",
    queueFor: (project: string) => `for ${project}`,
  },

  how: {
    heading: "How this works",
    items: [
      {
        title: "One project at a time",
        body: "The server has 2 CPUs and each project is a full ML stack. Running two at once would make both slow, so visitors take turns instead, in a queue.",
      },
      {
        title: "The Docker socket is isolated",
        body: "Starting a stack needs Docker, which is effectively root. The only process that holds the Docker socket is a small agent with no open ports: it long-polls the control plane outbound over an internal network for what should run. This public site can only change that desired state, never reach Docker.",
      },
      {
        title: "Started isn't ready",
        body: "A container being up says nothing about whether the model has loaded. You are only sent into a project after its health check passes, so you never land on a half-booted page.",
      },
    ],
  },

  interstitial: {
    back: "All projects",
    unknownProject: "There's no project with that id. Pick one from the catalog.",
    demo: "Watch the recorded demo",
    demoNote: "The demo needs no server and no waiting.",
    eta: (n: number) => `Boots in ${seconds(n)} once it's your turn.`,
    start: (project: string) => `Run ${project} live`,
    startWhy:
      "Starting loads the whole stack onto a shared 2-CPU box, which is why it takes a moment.",
    join: (project: string) => `Join the queue for ${project}`,
    busy: (running: string, holder: string) =>
      `${running} is running for ${holder}. The box runs one stack at a time because it only has 2 CPUs.`,
    busyQueue: (n: number) =>
      n === 0 ? "Nobody is waiting yet." : n === 1 ? "1 visitor is waiting." : `${n} visitors are waiting.`,
    busyHint: (l: LeaseTimes) =>
      `Joining the queue holds your place. Each turn is ${minutes(l.window_s)} from when the project is ready, then a ${minutes(l.grace_s)} handoff warning. ${idleRule(l)}`,
    queued: {
      heading: "You're in the queue",
      position: (n: number, alias: string) => `Position ${n}, as ${alias}.`,
      forProject: (project: string) => `Waiting to run ${project}.`,
      estimate: (position: number, l: LeaseTimes) =>
        `Estimated wait: ${queueEstimate(position, l)}. That is an upper bound: each turn is ${minutes(l.window_s)} plus a ${mins(l.grace_s)}-minute handoff, and turns often end earlier. ${idleRule(l)}`,
      leave: "Leave the queue",
      stayHint:
        "You can leave this tab open. It redirects you as soon as the project is ready.",
    },
    email: {
      label: "Email (optional)",
      why: "It's only used to tell you when your turn comes up or your project is ready. Nothing else, no list, and it isn't required.",
      submit: "Notify me",
      saved: "Saved. We'll email you when it's your turn.",
    },
    starting: {
      heading: (project: string) => `Starting ${project}`,
      why: "Loading models and warming caches on a 2-CPU box takes a while. Started isn't ready: we wait for the stack's health check before sending you in, so you never see a broken page.",
      progress: "Boot progress",
      pct: (n: number) => `${n}%`,
      overrun:
        "Taking a little longer than expected. The bar holds at 95% until the health check actually passes.",
    },
    ready: {
      heading: (project: string) => `${project} is ready`,
      opening: "Opening it now...",
    },
    switchTo: {
      running: (project: string) => `You're running ${project}.`,
      why: "Only one project can run at a time. Switching stops it and starts the other.",
      button: (project: string) => `Switch to ${project}`,
      keep: (project: string) => `Back to ${project}`,
    },
    stop: "Stop and free the box",
    stopWhy: "Stopping hands the box to the next visitor sooner.",
    working: "Working...",
  },

  notice: {
    demo: "Watch the recorded demo instead",
    dismiss: "Dismiss",
  },

  errors: {
    generic: "Something went wrong, and the server didn't say why. Try again in a moment.",
    network: "Couldn't reach the server. Check your connection and try again.",
  },

  announce: {
    idle: "The box is idle.",
    running: (project: string) => `${project} is running.`,
    starting: (project: string) => `${project} is starting.`,
    queued: (position: number) => `You are number ${position} in the queue.`,
  },

  admin: {
    heading: "Owner console",
    intro: "This area is for the site owner. It needs the owner secret.",
    secretLabel: "Owner secret",
    login: "Sign in",
    loginWhy:
      "Sign-in attempts are rate limited so the secret can't be guessed by brute force.",
    overview: "Overview",
    state: "Lease state",
    sessions: "Sessions",
    visits: "Recent visits",
    observed: "Agent reports",
    observedWhy: "The agent's latest observed states, newest first. Kept in memory, so a restart clears them.",
    noObserved: "No reports since the control plane started.",
    report: (r: { generation: number; stack_id: string | null; status: string; source: string }) =>
      `generation ${r.generation}: ${r.stack_id ?? "nothing"} ${r.status}${r.source === "watchdog" ? " (boot watchdog)" : ""}`,
    signOut: "Sign out",
    signOutWhy: "Sign out before opening a project: project pages share this origin.",
    noSessions: "No sessions yet.",
    noVisits: "No visits yet.",
    forceStop: "Force stop",
    forceStopWhy: "Stops the running stack immediately and frees the box, whoever holds it.",
    clearQueue: "Clear queue",
    clearQueueWhy: "Removes everyone waiting. They'll need to re-join.",
    refresh: "Refresh",
    done: "Done.",
  },

  notFound: {
    heading: "Page not found",
    body: "There's nothing at this address. It may have moved, or the link may be mistyped.",
    home: "Back to the projects",
  },
}

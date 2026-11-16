/** Every user-facing string lives here so the voice can be edited in one place. */

/** One visitor's turn, and the pause between visitors. Editable in one place. */
export const TURN_MIN = 15
export const HANDOFF_MIN = 3

const queueEstimate = (position: number): string =>
  `up to ~${position * (TURN_MIN + HANDOFF_MIN)} min`

const seconds = (n: number): string => `about ${n} seconds`

export const copy = {
  siteName: "The lab",
  skipLink: "Skip to content",
  nav: { catalog: "Projects", admin: "Owner" },
  tagline:
    "Five machine-learning projects, one small server. Run one live, or watch the recorded demo.",

  loading: "Loading the latest state of the box...",
  loadError:
    "Couldn't reach the control plane, so the status below may be stale. This page retries every few seconds on its own.",

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
    failed: (project: string) => `${project} failed its health check and was not opened.`,
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
        body: "Starting a stack needs Docker, which is effectively root. The only process that can reach the socket is a small agent that listens on a private socket, never on anything web-facing. This public site can only ask it to start or stop known projects.",
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
    busy: (project: string, holder: string) =>
      `${project} or another project is in use by ${holder}. The box runs one stack at a time because it only has 2 CPUs.`,
    busyQueue: (n: number) =>
      n === 0 ? "Nobody is waiting yet." : n === 1 ? "1 visitor is waiting." : `${n} visitors are waiting.`,
    busyHint:
      "Joining the queue holds your place. Each turn is 15 minutes, then a short handoff.",
    queued: {
      heading: "You're in the queue",
      position: (n: number, alias: string) => `Position ${n}, as ${alias}.`,
      forProject: (project: string) => `Waiting to run ${project}.`,
      estimate: (position: number) =>
        `Estimated wait: ${queueEstimate(position)}. That is an upper bound: each turn is ${TURN_MIN} minutes plus a ${HANDOFF_MIN}-minute handoff, and turns often end earlier.`,
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
    failed: {
      heading: (project: string) => `${project} didn't start`,
      body: "The stack didn't pass its health check, so we didn't send you into a broken page. This can happen when the box is short of memory. The recorded demo shows the same thing.",
      retry: "Try again",
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

  errors: {
    generic: "Something went wrong, and the server didn't say why. Try again in a moment.",
    network: "Couldn't reach the server. Check your connection and try again.",
  },

  announce: {
    idle: "The box is idle.",
    running: (project: string) => `${project} is running.`,
    starting: (project: string) => `${project} is starting.`,
    failed: (project: string) => `${project} failed to start.`,
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

import { Link } from "react-router"

import { copy } from "../copy"

export default function NotFound() {
  return (
    <section>
      <h2>{copy.notFound.heading}</h2>
      <p>{copy.notFound.body}</p>
      <p>
        <Link to="/">{copy.notFound.home}</Link>
      </p>
    </section>
  )
}

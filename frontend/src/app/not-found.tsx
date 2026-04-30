import Link from 'next/link'

export default function NotFound() {
  return (
    <main
      id="main-content"
      className="flex min-h-screen flex-col items-center justify-center gap-6 bg-white px-4 text-center"
    >
      <div className="flex flex-col items-center gap-2">
        <span className="text-6xl font-bold text-pfl-slate-200 select-none">404</span>
        <h1 className="text-2xl font-semibold text-pfl-slate-800">Page not found</h1>
        <p className="max-w-sm text-sm text-pfl-slate-500">
          The page you are looking for does not exist or has been moved.
        </p>
      </div>
      <Link
        href="/"
        className="rounded-md bg-pfl-blue-800 px-4 py-2 text-sm font-medium text-white hover:bg-pfl-blue-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pfl-blue-600 focus-visible:ring-offset-2"
      >
        Go home
      </Link>
    </main>
  )
}

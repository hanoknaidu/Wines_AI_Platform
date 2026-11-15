import { Link } from "react-router-dom";
import { Wordmark } from "@/components/shell/Wordmark";

export function NotFound({
  title = "Page not found",
  detail = "That address does not match anything here.",
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-md text-center">
        <Wordmark className="mb-8 justify-center" />
        <h1 className="text-lg font-semibold text-ink">{title}</h1>
        <p className="mt-2 text-why text-muted">{detail}</p>
        <Link
          to="/"
          className="mt-5 inline-block rounded-control border border-line bg-surface px-4 py-2 text-why text-ink hover:bg-sunken"
        >
          Start a new conversation
        </Link>
      </div>
    </main>
  );
}

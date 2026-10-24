import { RotateCw, Unplug } from "lucide-react";
import { useEffect, useRef } from "react";
import { Outlet, useLocation } from "react-router";

import { Button } from "../../components/Button";
import { Code } from "../../components/Code";
import { ErrorState } from "../../components/EmptyState";
import { Container } from "../../components/Page";
import { TooltipProvider } from "../../components/Tooltip";
import { Footer } from "./Footer";
import { MetaProvider, useMeta } from "./meta";
import { TopBar } from "./TopBar";

function ServerUnreachable() {
  const meta = useMeta();
  return (
    <Container className="py-12">
      <ErrorState
        icon={Unplug}
        title="Can't reach the SecuLayer server."
        help={
          <>
            Is <Code>./run.sh</Code> still running?
          </>
        }
        action={
          <Button variant="secondary" icon={RotateCw} onClick={meta.retry}>
            Try again
          </Button>
        }
      />
    </Container>
  );
}

function Main() {
  const meta = useMeta();
  const { pathname, hash } = useLocation();
  const previousPath = useRef(pathname);

  // A new page starts at the top, unless the link names a section (/how#patterns).
  useEffect(() => {
    const target = hash ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
    if (target) target.scrollIntoView();
    else window.scrollTo(0, 0);
    // Move keyboard and screen-reader users into the new page after navigation.
    // Keep initial-load and same-page controls' focus intact.
    if (previousPath.current !== pathname) {
      document.getElementById("main")?.focus({ preventScroll: true });
    }
    previousPath.current = pathname;
  }, [pathname, hash]);

  return (
    <main id="main" tabIndex={-1} className="flex-1">
      {meta.status === "error" ? <ServerUnreachable /> : <Outlet />}
    </main>
  );
}

/** The frame on every screen: top bar, page, footer. */
export function AppShell() {
  return (
    <MetaProvider>
      <TooltipProvider delayDuration={300}>
        <div className="flex min-h-screen flex-col bg-page">
          <a
            href="#main"
            className="sr-only rounded-control bg-page px-4 py-2 text-small font-semibold text-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:border focus:border-border-control"
          >
            Skip to main content
          </a>
          <TopBar />
          <Main />
          <Footer />
        </div>
      </TooltipProvider>
    </MetaProvider>
  );
}

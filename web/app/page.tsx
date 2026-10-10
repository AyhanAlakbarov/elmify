import { Nav } from "./_components/nav";
import { Hero } from "./_components/hero";
import { Closing, Compare, DashboardSection, Features, Footer, Funders, Principles } from "./_components/sections";

export default function Home() {
  return (
    <>
      <Nav />
      <main id="main">
        <Hero />
        <Funders />
        <DashboardSection />
        <Features />
        <Compare />
        <Principles />
        <Closing />
      </main>
      <Footer />
    </>
  );
}

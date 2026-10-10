import { Nav } from "./_components/nav";
import { Hero } from "./_components/hero";
import { Agencies, Closing, Faq, FeatureStrip, Footer, HowItWorks, Product } from "./_components/sections";

export default function Home() {
  return (
    <>
      <Nav />
      <main id="main">
        <Hero />
        <FeatureStrip />
        <HowItWorks />
        <Product />
        <Agencies />
        <Faq />
        <Closing />
      </main>
      <Footer />
    </>
  );
}

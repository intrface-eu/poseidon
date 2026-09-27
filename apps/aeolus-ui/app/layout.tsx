import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "AEOLUS · Local evidence monitor",
  description: "Local passive acoustic evidence review for Poseidon Trident.",
};

const DESIGN_CONTRACT = `
THESIS: A revision-controlled inspection traveler for passive acoustic evidence; it refuses the category-default dashboard of oversized status cards.
OWN-WORLD: Daylight off-white and cool gray surfaces, graphite ink, one measured teal accent, thin solid rules, stamped state tags, dense tables, and a split inspector built from native controls.
STORY: The operator unlocks a local workspace, imports evidence, watches processing reach a terminal state, selects a candidate, checks source context and waveform, then persists a human observation.
FIRST VIEWPORT: A slim utility header sits above a three-part workbench: recording navigation at left, filter and event register in the center, and the active evidence inspection panel at right. The empty state keeps Load synthetic demo and Import WAV + manifest visible in the work area.
FORM: Quality-control inspection traveler, fourth of seven grounded directions, seed 326c98b2.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
`.trim();

function ContractComment() {
  const source = `document.body.insertBefore(document.createComment(${JSON.stringify(DESIGN_CONTRACT)}),document.body.firstChild);`;
  return <script dangerouslySetInnerHTML={{ __html: source }} />;
}

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <ContractComment />
        {children}
      </body>
    </html>
  );
}

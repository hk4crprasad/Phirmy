"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import { CirclePlay } from "lucide-react";
import { Dialog } from "./ui";
import { LoadingMark } from "./loading-state";

const TourPlayer = dynamic(() => import("./motion/product-tour-player"), {
  ssr: false,
  loading: () => (
    <div className="tour-poster" role="status">
      <LoadingMark />
      <span>Opening the walkthrough…</span>
    </div>
  ),
});

export default function ProductTour({ card = false }: { card?: boolean }) {
  const [open, setOpen] = useState(false);
  const button = (
    <button
      className={"btn " + (card ? "small" : "subtle tour-trigger")}
      onClick={() => setOpen(true)}
      aria-label="Watch product tour"
    >
      <CirclePlay size={16} />
      {card ? "Watch" : "Take a 16-second tour"}
    </button>
  );
  return (
    <>
      {card ? (
        <div className="tour-card">
          <CirclePlay size={24} strokeWidth={1.4} />
          <div>
            <strong>A little guidance, if you need it.</strong>
            <p>See the path from knowledge to a conversation.</p>
          </div>
          {button}
        </div>
      ) : (
        button
      )}
      {open && (
        <div className="tour-dialog">
          <Dialog
            title="From knowledge to conversation"
            close={() => setOpen(false)}
          >
            <TourPlayer />
          </Dialog>
        </div>
      )}
    </>
  );
}

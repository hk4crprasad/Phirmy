import type { Row } from "@/lib/api";

type Checkout = {
  open: () => void;
  on?: (name: string, callback: (result: Row) => void) => void;
};
type Constructor = new (options: Row) => Checkout;
declare global {
  interface Window {
    Razorpay?: Constructor;
  }
}
let loading: Promise<Constructor> | null = null;

export function loadCheckout(): Promise<Constructor> {
  if (window.Razorpay) return Promise.resolve(window.Razorpay);
  if (!loading)
    loading = new Promise<Constructor>((resolve, reject) => {
      const script = document.createElement("script");
      const timer = window.setTimeout(() => {
        script.remove();
        loading = null;
        reject(
          Error(
            "Checkout took too long to load. Retry when your connection is ready.",
          ),
        );
      }, 15000);
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload = () => {
        window.clearTimeout(timer);
        if (window.Razorpay) resolve(window.Razorpay);
        else {
          loading = null;
          reject(Error("Checkout is unavailable."));
        }
      };
      script.onerror = () => {
        window.clearTimeout(timer);
        script.remove();
        loading = null;
        reject(Error("Checkout could not be loaded."));
      };
      document.head.appendChild(script);
    });
  return loading;
}

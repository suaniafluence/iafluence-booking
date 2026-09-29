import { Route, Routes } from "react-router-dom";
import Admin from "./pages/Admin";
import CheckoutRedirect from "./pages/CheckoutRedirect";
import NotFound from "./pages/NotFound";
import Reservation from "./pages/Reservation";

export default function App() {
  return (
    <Routes>
      <Route path="/reservation" element={<CheckoutRedirect />} />
      <Route path="/reservation/:token" element={<Reservation />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

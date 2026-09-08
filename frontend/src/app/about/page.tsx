import { Navbar } from "@/components/layout/navbar";
import { Footer } from "@/components/layout/footer";
import { Card, CardContent } from "@/components/ui/card";
import { Shield, Brain, MapPin, Users, Zap, Globe, Landmark, Sparkles } from "lucide-react";

export default function AboutPage() {
  return (
    <div className="min-h-screen flex flex-col bg-canvas">
      <Navbar />
      <main className="flex-1">
        <section className="relative overflow-hidden py-20">
          <div className="pointer-events-none absolute -top-32 left-1/2 h-96 w-[720px] -translate-x-1/2 rounded-full bg-primary-500/10 blur-3xl" aria-hidden="true" />
          <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-3xl text-center">
              <div className="mb-6 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-600 text-white shadow-lg">
                <Landmark className="h-7 w-7" />
              </div>
              <h1 className="text-4xl font-semibold tracking-tight text-slate-900 md:text-5xl">
                About CivicAgent
              </h1>
              <p className="mt-5 text-lg leading-7 text-slate-500">
                CivicAgent is an autonomous civic governance platform designed to bridge the gap
                between citizen complaints and municipal resolution. By leveraging artificial
                intelligence, geospatial analysis, and real-time coordination, we aim to make
                cities more responsive and communities more connected — with a human official
                verifying every automated recommendation.
              </p>
            </div>
          </div>
        </section>

        <section className="pb-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <h2 className="mb-12 text-center text-3xl font-semibold tracking-tight text-slate-900">
              Our Mission
            </h2>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {[
                { icon: <Brain className="h-6 w-6" />, title: "AI-First Approach", description: "Every complaint is analyzed, enriched, and prioritized using cutting-edge AI." },
                { icon: <MapPin className="h-6 w-6" />, title: "Geospatial Intelligence", description: "Location-aware analysis using PostGIS for contextual understanding." },
                { icon: <Users className="h-6 w-6" />, title: "Citizen-Centric", description: "Designed around citizen needs with transparent tracking and communication." },
                { icon: <Zap className="h-6 w-6" />, title: "Rapid Response", description: "Automated prioritization and dispatch for faster resolution times." },
                { icon: <Shield className="h-6 w-6" />, title: "Verified Quality", description: "AI-assisted verification ensures genuine resolution before closure." },
                { icon: <Globe className="h-6 w-6" />, title: "Human Oversight", description: "AI recommends, officials decide — every decision keeps a full audit trail." },
              ].map((item, index) => (
                <Card key={index} className="h-full transition-shadow hover:shadow-card-hover">
                  <CardContent className="p-6">
                    <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                      {item.icon}
                    </span>
                    <h3 className="text-lg font-semibold text-slate-900">{item.title}</h3>
                    <p className="mt-1.5 text-sm text-slate-500">{item.description}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        <section className="border-t border-border-soft bg-surface py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <h2 className="mb-12 text-center text-3xl font-semibold tracking-tight text-slate-900">
              Technology Stack
            </h2>
            <div className="mx-auto grid max-w-4xl grid-cols-1 gap-6 md:grid-cols-2">
              <Card>
                <CardContent className="p-6">
                  <h3 className="mb-3 font-semibold text-slate-900">Backend</h3>
                  <ul className="space-y-2 text-sm text-slate-500">
                    <li className="flex items-center gap-2"><Shield className="h-4 w-4 text-primary-500" /> Python, FastAPI, SQLAlchemy</li>
                    <li className="flex items-center gap-2"><MapPin className="h-4 w-4 text-primary-500" /> PostgreSQL + PostGIS + pgvector</li>
                    <li className="flex items-center gap-2"><Zap className="h-4 w-4 text-primary-500" /> Redis for caching and queues</li>
                    <li className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-ai-500" /> Groq LLM for AI analysis</li>
                  </ul>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-6">
                  <h3 className="mb-3 font-semibold text-slate-900">Frontend</h3>
                  <ul className="space-y-2 text-sm text-slate-500">
                    <li className="flex items-center gap-2"><Globe className="h-4 w-4 text-primary-500" /> Next.js, React, TypeScript</li>
                    <li className="flex items-center gap-2"><Zap className="h-4 w-4 text-primary-500" /> Tailwind CSS + token design system</li>
                    <li className="flex items-center gap-2"><Brain className="h-4 w-4 text-ai-500" /> Motion & data visualization</li>
                    <li className="flex items-center gap-2"><Users className="h-4 w-4 text-primary-500" /> Real-time WebSocket updates</li>
                  </ul>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
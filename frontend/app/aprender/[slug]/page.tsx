import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LessonView } from "@/components/learn/LessonView";
import { LESSONS, findLesson } from "@/lib/learn/lessons";

export function generateStaticParams() {
  return LESSONS.map((l) => ({ slug: l.slug }));
}

export const dynamicParams = false;

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const found = findLesson(slug);
  return found ? { title: found.lesson.title, description: found.lesson.summary } : {};
}

export default async function LessonPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!findLesson(slug)) notFound();
  return <LessonView slug={slug} />;
}

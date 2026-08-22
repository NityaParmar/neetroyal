import { Router, Request, Response } from "express";
import axios from "axios";
import { prisma } from "@repo/db"; // Keeping Yash's DB for his /sample route

const PYTHON_AI_URL = process.env.PYTHON_AI_URL || "http://127.0.0.1:8000";
const router = Router();

// Keep Yash's /sample route for his dashboard stats
router.get("/sample", async (_req: Request, res: Response): Promise<void> => {
  try {
    const totalQuestions = await prisma.question.count();
    const subjects = await prisma.question.groupBy({ by: ["subject"], _count: { id: true } });
    res.status(200).json({ success: true, totalQuestions, subjects: subjects.map((s) => ({ subject: s.subject, count: s._count.id })) });
  } catch {
    res.status(500).json({ success: false, error: "Database error" });
  }
});

// INTEGRATION: Fetch live questions from Aditya's AI Microservice
router.get("/random", async (req: Request, res: Response): Promise<void> => {
  const limit = Math.min(Number(req.query.limit) || 10, 20);
  const subject = req.query.subject as string | undefined;

  try {
    let url = `${PYTHON_AI_URL}/match/questions?count=${limit}`;
    if (subject) url += `&subject=${subject}`;

    const aiResponse = await axios.get(url);
    
    // Transform Aditya's flat format into Yash's expected nested format
    const formattedQuestions = aiResponse.data.map((q: any) => ({
      id: q.id.toString(),
      questionText: q.question_text,
      options: [q.option_a, q.option_b, q.option_c, q.option_d],
      subject: q.subject,
      topic: q.topic,
      difficulty: "MEDIUM" // Defaulting since AI doesn't return difficulty yet
    }));

    res.status(200).json({ success: true, questions: formattedQuestions });
  } catch (error: any) {
    console.error("AI Microservice Error:", error?.message);
    res.status(502).json({ success: false, error: "AI Engine unavailable" });
  }
});

export default router;
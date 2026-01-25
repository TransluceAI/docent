'use client';

import React, { useState } from 'react';
import axios from 'axios';
import { useParams } from 'next/navigation';
import { Loader2 } from 'lucide-react';

import { apiRestClient } from '@/app/services/apiService';
import { TextWithCitations } from '@/components/CitationRenderer';
import { InlineCitation } from '@/app/types/citationTypes';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import UuidPill from '@/components/UuidPill';

type Ambiguity = {
  rank?: number | string;
  ambiguity?: string;
  importance_rationale?: string;
  frequency?: string;
  example_agent_run_ids?: string[];
};

type QuestionOption = {
  title?: string | null;
  title_citations?: InlineCitation[];
  description?: string | null;
  description_citations?: InlineCitation[];
};

type FramedQuestion = {
  ambiguity?: Ambiguity | null;
  agent_run_id?: string | null;
  quote_title?: string | null;
  framed_question?: string | null;
  framed_question_citations?: InlineCitation[];
  question_context?: string | null;
  question_context_citations?: InlineCitation[];
  example_options?: QuestionOption[];
  error?: string | null;
};

type QaRubricElicitationResponse = {
  questions: FramedQuestion[];
  sampled_agent_run_ids: string[];
};

export default function QaRubricElicitationPanel() {
  const { collection_id: collectionId } = useParams<{
    collection_id: string;
  }>();

  const [rubricDescription, setRubricDescription] = useState('');
  const [numSamples, setNumSamples] = useState(50);
  const [topK, setTopK] = useState(10);
  const [questions, setQuestions] = useState<FramedQuestion[]>([]);
  const [sampledIds, setSampledIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<
    Record<number, number | 'custom'>
  >({});
  const [customResponses, setCustomResponses] = useState<
    Record<number, string>
  >({});

  const handleRun = async () => {
    if (!collectionId) return;
    setIsLoading(true);
    setError(null);
    setQuestions([]);
    setSampledIds([]);

    try {
      const response = await apiRestClient.post<QaRubricElicitationResponse>(
        `/qa/${collectionId}/rubric-elicitation`,
        {
          rubric_description: rubricDescription,
          num_samples: numSamples,
          top_k: topK,
        }
      );
      setQuestions(response.data.questions || []);
      setSampledIds(response.data.sampled_agent_run_ids || []);
    } catch (err) {
      const message = axios.isAxiosError(err)
        ? err.response?.data?.detail || err.message
        : 'Failed to run rubric elicitation.';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOptionClick = (questionIndex: number, optionIndex: number) => {
    console.log(
      `Question ${questionIndex + 1}: Selected option ${optionIndex + 1}`
    );
    setSelectedOptions((prev) => ({ ...prev, [questionIndex]: optionIndex }));
  };

  const handleCustomOptionClick = (questionIndex: number) => {
    console.log(
      `Question ${questionIndex + 1}: Selected "Type your own response"`
    );
    setSelectedOptions((prev) => ({ ...prev, [questionIndex]: 'custom' }));
  };

  const handleCustomResponseChange = (questionIndex: number, value: string) => {
    setCustomResponses((prev) => ({ ...prev, [questionIndex]: value }));
  };

  const isRunDisabled = isLoading || rubricDescription.trim().length === 0;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
      <div className="container mx-auto py-4 px-3 max-w-screen-xl">
        <div className="space-y-1 mb-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold tracking-tight">
                QA Rubric Elicitation
              </div>
              <div className="text-xs text-muted-foreground">
                Generate ambiguity questions from sampled agent runs.
              </div>
            </div>
            <Button onClick={handleRun} disabled={isRunDisabled}>
              {isLoading ? (
                <span className="inline-flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Running
                </span>
              ) : (
                'Run prototype'
              )}
            </Button>
          </div>
        </div>

        <Card className="border border-border/60">
          <CardHeader>
            <CardTitle className="text-sm">Inputs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="rubric-description">Rubric description</Label>
              <Textarea
                id="rubric-description"
                value={rubricDescription}
                onChange={(event) => setRubricDescription(event.target.value)}
                placeholder="Paste rubric description text here..."
                className="min-h-[160px]"
              />
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="num-samples">Number of samples</Label>
                <Input
                  id="num-samples"
                  type="number"
                  min={1}
                  value={numSamples}
                  onChange={(event) =>
                    setNumSamples(
                      Number.isFinite(Number(event.target.value))
                        ? Math.max(1, Number(event.target.value))
                        : 1
                    )
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="top-k">Top K ambiguities</Label>
                <Input
                  id="top-k"
                  type="number"
                  min={1}
                  value={topK}
                  onChange={(event) =>
                    setTopK(
                      Number.isFinite(Number(event.target.value))
                        ? Math.max(1, Number(event.target.value))
                        : 1
                    )
                  }
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Separator className="my-6" />

        {error && (
          <div className="text-red-500 text-sm mb-4 p-3 bg-red-50 rounded">
            {error}
          </div>
        )}

        {!isLoading && questions.length === 0 && !error && (
          <div className="text-center py-8 text-muted-foreground text-xs">
            No questions yet. Provide a rubric description and run the
            prototype.
          </div>
        )}

        {sampledIds.length > 0 && (
          <div className="text-xs text-muted-foreground mb-3">
            Sampled {sampledIds.length} agent runs.
          </div>
        )}

        <div className="space-y-4">
          {questions.map((question, index) => {
            return (
              <Card
                key={`question-${index}`}
                className="border border-border/60"
              >
                <CardHeader className="space-y-2">
                  <CardTitle className="text-sm">
                    {`Question ${index + 1}`}
                  </CardTitle>
                  {question.quote_title && (
                    <div className="text-sm font-medium text-foreground">
                      {question.quote_title}
                    </div>
                  )}
                  {question.agent_run_id && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>Agent run</span>
                      <UuidPill uuid={question.agent_run_id} stopPropagation />
                    </div>
                  )}
                </CardHeader>
                <CardContent className="space-y-4">
                  {question.error ? (
                    <div className="text-red-500 text-xs">{question.error}</div>
                  ) : (
                    <>
                      <div className="space-y-2">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Question
                        </div>
                        {question.framed_question ? (
                          <TextWithCitations
                            text={question.framed_question}
                            citations={question.framed_question_citations || []}
                          />
                        ) : (
                          <div className="text-xs text-muted-foreground">
                            No question returned.
                          </div>
                        )}
                      </div>

                      <div className="space-y-2">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Context
                        </div>
                        {question.question_context ? (
                          <TextWithCitations
                            text={question.question_context}
                            citations={
                              question.question_context_citations || []
                            }
                          />
                        ) : (
                          <div className="text-xs text-muted-foreground">
                            No context returned.
                          </div>
                        )}
                      </div>

                      <div className="space-y-2">
                        <div className="text-xs uppercase tracking-wide text-muted-foreground">
                          Example options
                        </div>
                        {question.example_options &&
                        question.example_options.length > 0 ? (
                          <div className="space-y-2">
                            {question.example_options.map(
                              (option, optionIndex) => (
                                <Button
                                  key={`option-${index}-${optionIndex}`}
                                  variant={
                                    selectedOptions[index] === optionIndex
                                      ? 'default'
                                      : 'outline'
                                  }
                                  className="w-full justify-start text-left h-auto py-2 px-3"
                                  onClick={() =>
                                    handleOptionClick(index, optionIndex)
                                  }
                                >
                                  <div className="space-y-1">
                                    <div className="font-medium text-sm">
                                      <TextWithCitations
                                        text={
                                          option.title?.trim() ||
                                          `Option ${optionIndex + 1}`
                                        }
                                        citations={option.title_citations || []}
                                      />
                                    </div>
                                    {option.description && (
                                      <div className="text-xs opacity-70">
                                        <TextWithCitations
                                          text={option.description}
                                          citations={
                                            option.description_citations || []
                                          }
                                        />
                                      </div>
                                    )}
                                  </div>
                                </Button>
                              )
                            )}
                            <Button
                              variant={
                                selectedOptions[index] === 'custom'
                                  ? 'default'
                                  : 'outline'
                              }
                              className="w-full justify-start text-left h-auto py-2 px-3"
                              onClick={() => handleCustomOptionClick(index)}
                            >
                              <span className="font-medium text-sm">
                                Type your own response
                              </span>
                            </Button>
                            {selectedOptions[index] === 'custom' && (
                              <Textarea
                                placeholder="Enter your custom response..."
                                value={customResponses[index] || ''}
                                onChange={(e) =>
                                  handleCustomResponseChange(
                                    index,
                                    e.target.value
                                  )
                                }
                                className="mt-2"
                              />
                            )}
                          </div>
                        ) : (
                          <div className="text-xs text-muted-foreground">
                            No example options returned.
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}

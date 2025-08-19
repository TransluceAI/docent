'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ArrowRight } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { toast } from '@/hooks/use-toast';
import { apiRestClient } from '@/app/services/apiService';

interface OnboardingData {
  institution: string;
  role: string;
  task: string;
  helpType: string;
  agentFrameworks: string;
  discoverySource: string;
}

interface QuestionOption {
  id: string;
  label: string;
  description?: string;
}

interface Question {
  id: string;
  title: string;
  type?: 'text';
  options?: QuestionOption[];
}

const INSTITUTION_OPTIONS: QuestionOption[] = [
  {
    id: 'university',
    label: 'University',
    description: 'Academic institution or university',
  },
  {
    id: 'research_institution',
    label: 'Research Institution',
    description: 'Research organization or institute',
  },
  {
    id: 'tech_company',
    label: 'Technology Company',
    description: 'Software, AI, or tech company',
  },
  {
    id: 'government',
    label: 'Government Agency',
    description: 'Public sector organization',
  },
  {
    id: 'nonprofit',
    label: 'Non-profit Organization',
    description: 'Charitable or advocacy organization',
  },
  {
    id: 'independent',
    label: 'Independent Researcher/Consultant',
    description: 'Working independently',
  },
  { id: 'other', label: 'Other', description: 'Something else' },
];

const TASK_OPTIONS: QuestionOption[] = [
  {
    id: 'ai_evaluation',
    label: 'AI Agent Evaluation',
    description: 'Evaluating AI assistants or agents',
  },
  {
    id: 'conversation_analysis',
    label: 'Conversation Analysis',
    description: 'Analyzing chat transcripts or conversations',
  },
  {
    id: 'dataset_building',
    label: 'Dataset Building',
    description: 'Creating evaluation datasets',
  },
  {
    id: 'research',
    label: 'Research & Development',
    description: 'Academic or industry research',
  },
  {
    id: 'quality_assurance',
    label: 'Quality Assurance',
    description: 'Testing and quality control',
  },
  {
    id: 'product_development',
    label: 'Product Development',
    description: 'Building AI-powered products',
  },
  { id: 'other', label: 'Other', description: 'Something else' },
];

const HELP_TYPE_OPTIONS: QuestionOption[] = [
  {
    id: 'automated_evaluation',
    label: 'Automated Evaluation',
    description: 'Automated tools for assessment',
  },
  {
    id: 'manual_review',
    label: 'Manual Review Tools',
    description: 'Tools for human review and annotation',
  },
  {
    id: 'data_analysis',
    label: 'Data Analysis',
    description: 'Analytics and insights',
  },
  {
    id: 'research_insights',
    label: 'Research Insights',
    description: 'Research and academic insights',
  },
  {
    id: 'collaboration',
    label: 'Team Collaboration',
    description: 'Working with teams and stakeholders',
  },
  {
    id: 'reporting',
    label: 'Reporting & Visualization',
    description: 'Creating reports and visualizations',
  },
  { id: 'other', label: 'Other', description: 'Something else' },
];

const AGENT_FRAMEWORK_OPTIONS: QuestionOption[] = [
  { id: 'langchain', label: 'LangChain', description: 'LangChain framework' },
  { id: 'inspect', label: 'Inspect', description: 'Inspect framework' },
  {
    id: 'autogen',
    label: 'AutoGen',
    description: 'Microsoft AutoGen framework',
  },
  { id: 'crewai', label: 'CrewAI', description: 'CrewAI framework' },
  {
    id: 'semantic_kernel',
    label: 'Semantic Kernel',
    description: 'Microsoft Semantic Kernel',
  },
  {
    id: 'openai_assistants',
    label: 'OpenAI Assistants',
    description: 'OpenAI Assistants API',
  },
  {
    id: 'llamaindex',
    label: 'LlamaIndex',
    description: 'LlamaIndex framework',
  },
  {
    id: 'custom',
    label: 'Custom Framework',
    description: 'Custom or in-house solution',
  },
  { id: 'none', label: 'None', description: 'No framework' },
  { id: 'other', label: 'Other', description: 'Something else' },
];

const ROLE_OPTIONS: QuestionOption[] = [
  {
    id: 'researcher',
    label: 'Researcher',
    description: 'Academic or industry research',
  },
  { id: 'engineer', label: 'Engineer', description: 'Software or ML engineer' },
  {
    id: 'product_manager',
    label: 'Product Manager',
    description: 'Product management',
  },
  {
    id: 'data_scientist',
    label: 'Data Scientist',
    description: 'Data science and analytics',
  },
  {
    id: 'student',
    label: 'Student',
    description: 'Graduate or undergraduate student',
  },
  {
    id: 'consultant',
    label: 'Consultant',
    description: 'Independent consultant',
  },
  { id: 'manager', label: 'Manager', description: 'Team or project manager' },
  { id: 'other', label: 'Other', description: 'Something else' },
];

const DISCOVERY_OPTIONS: QuestionOption[] = [
  {
    id: 'social_media',
    label: 'Social Media',
    description: 'Twitter, LinkedIn, or other social platforms',
  },
  {
    id: 'conference',
    label: 'Conference or Event',
    description: 'Academic or industry conference',
  },
  {
    id: 'colleague',
    label: 'Colleague Recommendation',
    description: 'Recommended by someone I know',
  },
  {
    id: 'search',
    label: 'Search Engine',
    description: 'Found through Google or other search',
  },
  {
    id: 'paper',
    label: 'Research Paper',
    description: 'Mentioned in academic literature',
  },
  {
    id: 'news',
    label: 'News or Article',
    description: 'Featured in news or blog post',
  },
  { id: 'other', label: 'Other', description: 'Something else' },
];

export default function Onboarding2Page() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectParam = searchParams.get('redirect') || '';
  const [currentStep, setCurrentStep] = useState(1);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const otherInputRef = useRef<HTMLInputElement>(null);
  const [onboardingData, setOnboardingData] = useState<OnboardingData>({
    institution: '',
    role: '',
    task: '',
    helpType: '',
    agentFrameworks: '',
    discoverySource: '',
  });
  const [selectedOptions, setSelectedOptions] = useState({
    institution: '',
    role: '',
    task: [] as string[],
    helpType: [] as string[],
    agentFrameworks: [] as string[],
    discoverySource: '',
  });
  const [otherTexts, setOtherTexts] = useState({
    institution: '',
    role: '',
    task: '',
    helpType: '',
    agentFrameworks: '',
    discoverySource: '',
  });

  const totalSteps = 6;

  const questions: Question[] = [
    {
      id: 'institution',
      title: 'What organization are you with?',
      type: 'text',
    },
    {
      id: 'role',
      title: 'What is your role?',
      options: ROLE_OPTIONS,
    },
    {
      id: 'task',
      title: 'What are you working on?',
      options: TASK_OPTIONS,
    },
    {
      id: 'helpType',
      title: 'How are you hoping Docent can help?',
      options: HELP_TYPE_OPTIONS,
    },
    {
      id: 'agentFrameworks',
      title: 'Which frameworks do you use?',
      options: AGENT_FRAMEWORK_OPTIONS,
    },
    {
      id: 'discoverySource',
      title: 'How did you hear about us?',
      options: DISCOVERY_OPTIONS,
    },
  ];

  const handleNext = () => {
    if (currentStep < totalSteps) {
      setCurrentStep(currentStep + 1);
    } else {
      handleCompleteOnboarding();
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleCompleteOnboarding = async () => {
    try {
      // Save onboarding data to backend
      await apiRestClient.post('/onboarding', {
        institution: onboardingData.institution || null,
        role: onboardingData.role || null,
        task: onboardingData.task || null,
        help_type: onboardingData.helpType || null,
        agent_frameworks: onboardingData.agentFrameworks || null,
        discovery_source: onboardingData.discoverySource || null,
      });

      toast({
        title: 'Welcome to Docent!',
        description: 'Your account has been set up successfully.',
      });
      const redirectUrl = redirectParam || '/dashboard';
      router.push(redirectUrl);
    } catch (error) {
      console.error('Failed to complete onboarding:', error);
      toast({
        title: 'Error',
        description: 'Failed to complete onboarding. Please try again.',
        variant: 'destructive',
      });
    }
  };

  const handleOptionSelect = (
    questionId: keyof OnboardingData,
    optionId: string
  ) => {
    // Skip institution as it's now a text input
    if (questionId === 'institution') return;

    if (
      questionId === 'task' ||
      questionId === 'helpType' ||
      questionId === 'agentFrameworks'
    ) {
      // Multi-select for task, helpType, and agentFrameworks
      const field = questionId as 'task' | 'helpType' | 'agentFrameworks';
      setSelectedOptions((prev) => ({
        ...prev,
        [field]: prev[field].includes(optionId)
          ? prev[field].filter((id) => id !== optionId)
          : [...prev[field], optionId],
      }));

      // Update onboarding data
      const question = questions.find((q) => q.id === questionId);
      const currentSelection = selectedOptions[field];
      const selectedLabels = currentSelection.includes(optionId)
        ? currentSelection
            .filter((id) => id !== optionId)
            .map((id) => {
              const opt = question?.options?.find((o) => o.id === id);
              return opt?.label || '';
            })
        : [...currentSelection, optionId].map((id) => {
            const opt = question?.options?.find((o) => o.id === id);
            return opt?.label || '';
          });

      setOnboardingData((prev) => ({
        ...prev,
        [questionId]: selectedLabels.join(', '),
      }));

      // Focus input if "other" was selected
      if (optionId === 'other' && !currentSelection.includes('other')) {
        setTimeout(() => otherInputRef.current?.focus(), 0);
      }
    } else {
      // Single select for other questions
      const currentSelection = selectedOptions[questionId];

      if (currentSelection === optionId) {
        // Unselect if clicking on already selected option
        setSelectedOptions((prev) => ({
          ...prev,
          [questionId]: '',
        }));
        setOnboardingData((prev) => ({
          ...prev,
          [questionId]: '',
        }));
      } else {
        // Select new option
        setSelectedOptions((prev) => ({
          ...prev,
          [questionId]: optionId,
        }));

        if (optionId === 'other') {
          // Keep the existing other text
          setOnboardingData((prev) => ({
            ...prev,
            [questionId]: otherTexts[questionId],
          }));
          // Focus the input
          setTimeout(() => otherInputRef.current?.focus(), 0);
        } else {
          // Use the option label
          const question = questions.find((q) => q.id === questionId);
          const option = question?.options?.find((o) => o.id === optionId);
          setOnboardingData((prev) => ({
            ...prev,
            [questionId]: option?.label || '',
          }));
        }
      }
    }
  };

  const handleOtherTextChange = (
    questionId: keyof OnboardingData,
    value: string
  ) => {
    setOtherTexts((prev) => ({
      ...prev,
      [questionId]: value,
    }));

    if (selectedOptions[questionId] === 'other') {
      setOnboardingData((prev) => ({
        ...prev,
        [questionId]: value,
      }));
    }
  };

  const currentQuestion = questions[currentStep - 1];

  // Reset scroll to top when step changes
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, [currentStep]);

  return (
    <div
      ref={scrollContainerRef}
      className="h-screen bg-background overflow-y-auto"
    >
      <div className="container mx-auto py-12 px-4 max-w-2xl">
        <div className="space-y-12 pb-8">
          {/* Progress Bar */}
          <div className="space-y-3">
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>
                Step {currentStep} of {totalSteps}
              </span>
              <span>{Math.round((currentStep / totalSteps) * 100)}%</span>
            </div>
            <div className="relative h-3 w-full overflow-hidden rounded-full bg-secondary">
              <div
                className="h-full bg-primary transition-all duration-300 ease-in-out"
                style={{ width: `${(currentStep / totalSteps) * 100}%` }}
              />
            </div>
          </div>

          {/* Question Content */}
          <div className="space-y-8">
            <div className="text-center space-y-3">
              <h2 className="text-3xl font-bold tracking-tight">
                {currentQuestion.title}
              </h2>
            </div>

            {currentQuestion.type === 'text' ? (
              <div className="space-y-3">
                <Input
                  placeholder="e.g., Stanford University, Google, Microsoft Research, OpenAI..."
                  value={onboardingData.institution}
                  onChange={(e) => {
                    setOnboardingData((prev) => ({
                      ...prev,
                      institution: e.target.value,
                    }));
                  }}
                  className="text-base"
                />
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                {currentQuestion.options?.map((option) => (
                  <Card
                    key={option.id}
                    className={`cursor-pointer transition-all hover:shadow-md ${
                      option.id === 'other' ? 'col-span-2' : ''
                    } ${
                      currentQuestion.id === 'task' ||
                      currentQuestion.id === 'helpType' ||
                      currentQuestion.id === 'agentFrameworks'
                        ? (
                            currentQuestion.id === 'task'
                              ? selectedOptions.task.includes(option.id)
                              : currentQuestion.id === 'helpType'
                                ? selectedOptions.helpType.includes(option.id)
                                : selectedOptions.agentFrameworks.includes(
                                    option.id
                                  )
                          )
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                        : selectedOptions[
                              currentQuestion.id as keyof OnboardingData
                            ] === option.id
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                    }`}
                    onClick={() =>
                      handleOptionSelect(
                        currentQuestion.id as keyof OnboardingData,
                        option.id
                      )
                    }
                  >
                    <CardContent className="p-3">
                      <div className="flex items-center space-x-3">
                        {currentQuestion.id === 'task' ||
                        currentQuestion.id === 'helpType' ||
                        currentQuestion.id === 'agentFrameworks' ? (
                          // Checkbox for task, helpType, and agentFrameworks (multi-select)
                          <div
                            className={`w-4 h-4 border-2 flex-shrink-0 flex items-center justify-center text-xs font-bold ${
                              currentQuestion.id === 'task'
                                ? selectedOptions.task.includes(option.id)
                                  ? 'border-primary bg-primary text-white'
                                  : 'border-muted-foreground'
                                : currentQuestion.id === 'helpType'
                                  ? selectedOptions.helpType.includes(option.id)
                                    ? 'border-primary bg-primary text-white'
                                    : 'border-muted-foreground'
                                  : selectedOptions.agentFrameworks.includes(
                                        option.id
                                      )
                                    ? 'border-primary bg-primary text-white'
                                    : 'border-muted-foreground'
                            }`}
                          >
                            {(currentQuestion.id === 'task'
                              ? selectedOptions.task.includes(option.id)
                              : currentQuestion.id === 'helpType'
                                ? selectedOptions.helpType.includes(option.id)
                                : selectedOptions.agentFrameworks.includes(
                                    option.id
                                  )) && '✓'}
                          </div>
                        ) : (
                          // Radio button for other questions (single select)
                          <div
                            className={`w-4 h-4 rounded-full border-2 flex-shrink-0 ${
                              selectedOptions[
                                currentQuestion.id as keyof OnboardingData
                              ] === option.id
                                ? 'border-primary bg-primary'
                                : 'border-muted-foreground'
                            }`}
                          >
                            {selectedOptions[
                              currentQuestion.id as keyof OnboardingData
                            ] === option.id && (
                              <div className="w-2 h-2 bg-white rounded-full m-0.5" />
                            )}
                          </div>
                        )}
                        <div className="flex-1">
                          <h3 className="font-medium text-sm">
                            {option.label}
                          </h3>
                          {option.id === 'other' && (
                            <div className="mt-2">
                              <Input
                                ref={otherInputRef}
                                placeholder="Please specify..."
                                value={
                                  otherTexts[
                                    currentQuestion.id as keyof OnboardingData
                                  ]
                                }
                                onChange={(e) =>
                                  handleOtherTextChange(
                                    currentQuestion.id as keyof OnboardingData,
                                    e.target.value
                                  )
                                }
                                className={`text-sm h-9 ${
                                  (currentQuestion.id === 'task' &&
                                    selectedOptions.task.includes('other')) ||
                                  (currentQuestion.id === 'helpType' &&
                                    selectedOptions.helpType.includes(
                                      'other'
                                    )) ||
                                  (currentQuestion.id === 'agentFrameworks' &&
                                    selectedOptions.agentFrameworks.includes(
                                      'other'
                                    )) ||
                                  (currentQuestion.id !== 'task' &&
                                    currentQuestion.id !== 'helpType' &&
                                    currentQuestion.id !== 'agentFrameworks' &&
                                    selectedOptions[
                                      currentQuestion.id as keyof OnboardingData
                                    ] === 'other')
                                    ? 'bg-primary/10 border-primary/30'
                                    : ''
                                }`}
                                onClick={(e) => e.stopPropagation()}
                              />
                            </div>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>

          {/* Navigation Buttons */}
          <div className="flex justify-between pt-12 border-t">
            {currentStep > 1 && (
              <Button
                variant="ghost"
                onClick={handleBack}
                className="flex items-center gap-2"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
            )}
            {currentStep === 1 && <div></div>}

            <Button
              onClick={handleNext}
              className="flex items-center gap-2"
              size="lg"
            >
              {currentStep === totalSteps ? 'Complete Setup' : 'Continue'}
              {currentStep < totalSteps && <ArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

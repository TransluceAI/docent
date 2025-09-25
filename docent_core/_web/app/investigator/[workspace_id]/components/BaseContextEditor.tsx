'use client';

import React, { useState } from 'react';
import { Plus, Trash2, X, Copy, Settings } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { getNextForkName } from '@/lib/investigatorUtils';
import { JsonSchemaEditor } from './JsonSchemaEditor';

// Enhanced ToolCall interface with type discrimination
interface FunctionToolCall {
  id: string;
  function: string;
  type: 'function';
  arguments?: Record<string, unknown> | string;
  view?: {
    content: string;
    format: string;
  };
}

// Only function tool calls are allowed
type ToolCall = FunctionToolCall;

interface Message {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
}

// Tool parameter schema for function tools
export interface ToolParameters {
  type: 'object';
  properties: Record<string, any>;
  required: string[];
  additionalProperties?: boolean;
}

// Function tool that takes JSON schema parameters
export interface FunctionToolInfo {
  type: 'function';
  name: string;
  description: string;
  parameters: ToolParameters;
  strict?: boolean;
}

// Only function tool types are allowed
export type ToolInfo = FunctionToolInfo;

export interface BaseContextData {
  name: string;
  prompt: Message[];
  tools?: ToolInfo[];
}

interface BaseContextEditorProps {
  initialValue?: BaseContextData;
  readOnly?: boolean;
  onSave?: (data: BaseContextData) => void;
  onFork?: (data: BaseContextData) => void;
  onDelete?: () => void;
  onCancel?: () => void; // Optional, required when not readOnly
  onClose?: () => void; // Optional, required when readOnly
}

// Reuse the role styling from MessageBox component
const getRoleStyle = (role: string) => {
  switch (role) {
    case 'user':
      return 'bg-gray-50 dark:bg-gray-900/50 border-l-4 border-gray-300 dark:border-gray-700';
    case 'assistant':
      return 'bg-blue-50 dark:bg-blue-950/30 border-l-4 border-blue-300 dark:border-blue-700';
    case 'system':
      return 'bg-orange-50 dark:bg-orange-950/30 border-l-4 border-orange-300 dark:border-orange-700';
    default:
      return 'bg-gray-50 dark:bg-gray-900/50 border-l-4 border-gray-300 dark:border-gray-700';
  }
};

const getRoleBadgeStyle = (role: string) => {
  switch (role) {
    case 'user':
      return 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300';
    case 'assistant':
      return 'bg-blue-200 dark:bg-blue-800 text-blue-700 dark:text-blue-300';
    case 'system':
      return 'bg-orange-200 dark:bg-orange-800 text-orange-700 dark:text-orange-300';
    default:
      return 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300';
  }
};

export default function BaseContextEditor({
  initialValue,
  readOnly = false,
  onSave,
  onFork,
  onDelete,
  onCancel,
  onClose,
}: BaseContextEditorProps) {
  const [name, setName] = useState(initialValue?.name || '');
  const [messages, setMessages] = useState<Message[]>(() => {
    if (!initialValue?.prompt) {
      return [{ role: 'user', content: '' }];
    }

    // Deep clone the prompt to avoid read-only array issues
    return initialValue.prompt.map((msg) => {
      const clonedMsg: Message = {
        role: msg.role,
        content: msg.content,
      };

      // Deep clone tool_calls if they exist
      if (msg.tool_calls) {
        clonedMsg.tool_calls = msg.tool_calls.map((tc) => ({ ...tc }));
      }

      if (msg.tool_call_id) {
        clonedMsg.tool_call_id = msg.tool_call_id;
      }

      return clonedMsg;
    });
  });
  const [tools, setTools] = useState<ToolInfo[]>(
    initialValue?.tools?.map((tool): ToolInfo => {
      // All tools are function tools
      let parameters: ToolParameters;

      if (!('parameters' in tool) || !tool.parameters) {
        // No parameters provided, use default
        parameters = createDefaultJsonSchema();
      } else if (
        tool.parameters.properties &&
        Object.values(tool.parameters.properties).length > 0 &&
        typeof Object.values(tool.parameters.properties)[0] === 'object' &&
        'input_schema' in (Object.values(tool.parameters.properties)[0] as any)
      ) {
        // Convert from Docent format to JSON Schema format
        parameters = {
          type: 'object',
          properties: Object.entries(tool.parameters.properties).reduce(
            (acc, [propName, propDef]: [string, any]) => {
              acc[propName] = propDef.input_schema || {
                type: 'string',
                description: propDef.description || '',
              };
              return acc;
            },
            {} as Record<string, any>
          ),
          required: tool.parameters.required || [],
          additionalProperties: tool.parameters.additionalProperties ?? false,
        };
      } else {
        // Already in JSON Schema format
        parameters = tool.parameters as ToolParameters;
      }

      const functionTool: FunctionToolInfo = {
        type: 'function',
        name: tool.name,
        description: tool.description,
        parameters,
        strict: 'strict' in tool ? tool.strict : undefined,
      };
      return functionTool;
    }) || []
  );
  const [errors, setErrors] = useState<{
    name?: string;
    messages?: { [key: number]: string };
    tools?: { [key: number]: string };
    toolCalls?: { [messageIndex: number]: { [toolCallIndex: number]: string } };
  }>({});
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  // Use onClose if provided (for readOnly mode), otherwise onCancel
  const handleClose = () => {
    if (onClose) {
      onClose();
    } else if (onCancel) {
      onCancel();
    }
  };

  const validateForm = (): boolean => {
    const newErrors: typeof errors = {};

    // Validate name
    if (!name.trim()) {
      newErrors.name = 'Name is required';
    }

    // Validate messages
    const messageErrors: { [key: number]: string } = {};
    const toolCallErrors: {
      [messageIndex: number]: { [toolCallIndex: number]: string };
    } = {};

    messages.forEach((message, index) => {
      // Allow assistant messages with tool calls and tool messages to have empty content
      const allowsEmptyContent =
        (message.role === 'assistant' &&
          message.tool_calls &&
          message.tool_calls.length > 0) ||
        message.role === 'tool';

      if (!message.content.trim() && !allowsEmptyContent) {
        messageErrors[index] = 'Message content is required';
      }

      // Validate tool calls for this message
      if (message.tool_calls && message.tool_calls.length > 0) {
        message.tool_calls.forEach((toolCall, toolCallIndex) => {
          // Validate that function tool calls have valid JSON arguments
          if (toolCall.type === 'function' && toolCall.arguments) {
            if (typeof toolCall.arguments === 'string') {
              try {
                // Try to parse the arguments as JSON
                JSON.parse(toolCall.arguments);
              } catch (e) {
                if (!toolCallErrors[index]) {
                  toolCallErrors[index] = {};
                }
                toolCallErrors[index][toolCallIndex] =
                  'Invalid JSON in arguments';
              }
            }
          }
        });
      }
    });

    if (Object.keys(messageErrors).length > 0) {
      newErrors.messages = messageErrors;
    }

    if (Object.keys(toolCallErrors).length > 0) {
      newErrors.toolCalls = toolCallErrors;
    }

    // Validate tools
    const toolErrors: { [key: number]: string } = {};
    tools.forEach((tool, index) => {
      if (!tool.name.trim()) {
        toolErrors[index] = 'Tool name is required';
      } else if (!tool.description.trim()) {
        toolErrors[index] = 'Tool description is required';
      }
    });

    if (Object.keys(toolErrors).length > 0) {
      newErrors.tools = toolErrors;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSave = () => {
    if (validateForm() && onSave) {
      // Transform tool calls to match backend expectations
      const transformedMessages = messages.map((m) => {
        const msg: any = {
          role: m.role,
          content: m.content.trim(),
        };

        // Handle tool calls transformation
        if (m.tool_calls && m.tool_calls.length > 0) {
          msg.tool_calls = m.tool_calls.map((tc) => {
            // For function tool calls, parse arguments as JSON
            let parsedArgs: any = {};
            if (tc.arguments) {
              if (typeof tc.arguments === 'string') {
                try {
                  parsedArgs = JSON.parse(tc.arguments);
                } catch (e) {
                  // If parsing fails, keep as string
                  parsedArgs = tc.arguments;
                }
              } else {
                parsedArgs = tc.arguments;
              }
            }
            return {
              id: tc.id,
              function: tc.function,
              type: 'function',
              arguments: parsedArgs,
            };
          });
        }

        if (m.tool_call_id) {
          msg.tool_call_id = m.tool_call_id;
        }

        return msg;
      });

      onSave({
        name: name.trim(),
        prompt: transformedMessages,
        tools:
          tools.length > 0
            ? tools.map((tool): ToolInfo => {
                // For function tools, convert JSON schema format to Docent ToolInfo format if needed
                const convertedParameters: ToolParameters = {
                  type: 'object',
                  properties: Object.entries(
                    tool.parameters.properties || {}
                  ).reduce(
                    (acc, [propName, propSchema]: [string, any]) => {
                      // Check if it's already in Docent format
                      if (propSchema.input_schema) {
                        acc[propName] = propSchema;
                      } else {
                        // Convert to Docent format
                        acc[propName] = {
                          name: propName,
                          description: propSchema.description || '',
                          input_schema: propSchema,
                        };
                      }
                      return acc;
                    },
                    {} as Record<string, any>
                  ),
                  required: tool.parameters.required || [],
                  additionalProperties:
                    tool.parameters.additionalProperties ?? false,
                };

                const functionTool: FunctionToolInfo = {
                  type: 'function',
                  name: tool.name,
                  description: tool.description,
                  parameters: convertedParameters,
                  strict: tool.strict,
                };
                return functionTool;
              })
            : undefined,
      });
    }
  };

  const handleFork = () => {
    if (onFork && initialValue) {
      // Deep clone the prompt to avoid read-only array issues
      const clonedPrompt = initialValue.prompt.map((msg) => {
        const clonedMsg: Message = {
          role: msg.role,
          content: msg.content,
        };

        // Deep clone tool_calls if they exist
        if (msg.tool_calls) {
          clonedMsg.tool_calls = msg.tool_calls.map((tc) => ({ ...tc }));
        }

        if (msg.tool_call_id) {
          clonedMsg.tool_call_id = msg.tool_call_id;
        }

        return clonedMsg;
      });

      const forkedData: BaseContextData = {
        ...initialValue,
        name: getNextForkName(initialValue.name),
        prompt: clonedPrompt,
        tools: initialValue.tools
          ? initialValue.tools.map((tool) => ({ ...tool }))
          : undefined,
      };
      onFork(forkedData);
    }
  };

  const addMessage = () => {
    // Default to alternating roles for better UX
    const lastRole = messages[messages.length - 1]?.role;
    const nextRole = lastRole === 'user' ? 'assistant' : 'user';
    setMessages([...messages, { role: nextRole, content: '' }]);
  };

  const addToolCall = (messageIndex: number) => {
    const newMessages = [...messages];
    const currentMessage = newMessages[messageIndex];

    // Create a new tool_calls array (or initialize if it doesn't exist)
    const newToolCalls = currentMessage.tool_calls
      ? [...currentMessage.tool_calls]
      : [];

    // Add the new tool call
    const newToolCall: FunctionToolCall = {
      id: `call_${Date.now()}`,
      function: '',
      type: 'function',
      arguments: {},
    };
    newToolCalls.push(newToolCall);

    // Create a new message object with the updated tool_calls
    newMessages[messageIndex] = {
      ...currentMessage,
      tool_calls: newToolCalls,
    };

    setMessages(newMessages);
  };

  const updateToolCall = (
    messageIndex: number,
    toolCallIndex: number,
    updates: Partial<ToolCall>
  ) => {
    const newMessages = [...messages];
    if (newMessages[messageIndex].tool_calls) {
      const currentToolCall =
        newMessages[messageIndex].tool_calls![toolCallIndex];

      // Create a new array to avoid read-only issues
      const newToolCalls = [...newMessages[messageIndex].tool_calls!];

      // Since we only have function type, no type switching logic needed
      // Just update the tool call with the new values
      newToolCalls[toolCallIndex] = {
        ...currentToolCall,
        ...updates,
      };

      // Assign the new array to avoid mutation issues
      newMessages[messageIndex] = {
        ...newMessages[messageIndex],
        tool_calls: newToolCalls,
      };

      setMessages(newMessages);
    }
  };

  const removeToolCall = (messageIndex: number, toolCallIndex: number) => {
    const newMessages = [...messages];
    if (newMessages[messageIndex].tool_calls) {
      // Create a new array to avoid mutation issues
      const newToolCalls = [...newMessages[messageIndex].tool_calls!];
      newToolCalls.splice(toolCallIndex, 1);

      newMessages[messageIndex] = {
        ...newMessages[messageIndex],
        tool_calls: newToolCalls,
      };

      setMessages(newMessages);
    }
  };

  const formatToolData = (toolCall: ToolCall): string => {
    // For function tool calls, format the arguments
    const args = toolCall.arguments;
    if (args === undefined || args === null) {
      return '';
    }
    if (typeof args === 'string') {
      return args;
    }
    try {
      return JSON.stringify(args, null, 2);
    } catch (error) {
      return String(args);
    }
  };

  const removeMessage = (index: number) => {
    if (messages.length > 1) {
      setMessages(messages.filter((_, i) => i !== index));
      // Clear error for this message if it exists
      if (errors.messages?.[index]) {
        const newMessageErrors = { ...errors.messages };
        delete newMessageErrors[index];
        setErrors({ ...errors, messages: newMessageErrors });
      }
    }
  };

  const updateMessage = (
    index: number,
    field: 'role' | 'content' | 'tool_call_id',
    value: string
  ) => {
    const newMessages = [...messages];
    if (field === 'role') {
      newMessages[index].role = value as
        | 'user'
        | 'assistant'
        | 'system'
        | 'tool';
    } else if (field === 'tool_call_id') {
      newMessages[index].tool_call_id = value;
    } else {
      newMessages[index].content = value;
    }
    setMessages(newMessages);

    // Clear error for this message if content is provided
    if (field === 'content' && value.trim() && errors.messages?.[index]) {
      const newMessageErrors = { ...errors.messages };
      delete newMessageErrors[index];
      setErrors({ ...errors, messages: newMessageErrors });
    }
  };

  const createDefaultJsonSchema = () => ({
    type: 'object' as const,
    properties: {},
    required: [],
    additionalProperties: false,
  });

  const addTool = () => {
    const newTool: FunctionToolInfo = {
      type: 'function',
      name: '',
      description: '',
      parameters: createDefaultJsonSchema(),
      strict: true,
    };
    setTools([...tools, newTool]);
  };

  const removeTool = (index: number) => {
    if (tools.length > 0) {
      setTools(tools.filter((_, i) => i !== index));
      // Clear error for this tool if it exists
      if (errors.tools?.[index]) {
        const newToolErrors = { ...errors.tools };
        delete newToolErrors[index];
        setErrors({ ...errors, tools: newToolErrors });
      }
    }
  };

  const updateTool = (
    index: number,
    field: 'name' | 'description' | 'type',
    value: string | 'function'
  ) => {
    const newTools = [...tools];
    const currentTool = newTools[index];

    if (field === 'type') {
      // Only function type is allowed, this is just kept for potential future tool types
      // No conversion needed since we only have function type
      return;
    }

    // Update name or description
    newTools[index] = {
      ...currentTool,
      [field]: value as string,
    };

    setTools(newTools);

    // Clear error for this tool if content is provided
    if ((value as string).trim() && errors.tools?.[index]) {
      const newToolErrors = { ...errors.tools };
      delete newToolErrors[index];
      setErrors({ ...errors, tools: newToolErrors });
    }
  };

  const updateToolParameters = (index: number, parameters: ToolParameters) => {
    const newTools = [...tools];
    const tool = newTools[index];
    // Only update parameters for function tools
    if (tool.type === 'function') {
      newTools[index] = { ...tool, parameters };
      setTools(newTools);
    }
  };

  return (
    <div className="flex flex-col h-full m-6">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b">
        <div>
          <h2 className="text-lg font-semibold">
            {readOnly
              ? 'View Base Context'
              : initialValue
                ? 'Edit Base Context'
                : 'New Base Context'}
          </h2>
          {readOnly && initialValue ? (
            <p className="text-xs text-muted-foreground mt-1">
              Read-only view of &quot;{initialValue.name}&quot;
            </p>
          ) : initialValue ? (
            <p className="text-xs text-muted-foreground mt-1">
              Note: Editing will create a new version of this context
            </p>
          ) : null}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleClose}
          className="h-8 w-8 p-0"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Form Content */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {/* Name Field */}
        <div className="space-y-2">
          <Label htmlFor="context-name">{readOnly ? 'Name' : 'Name *'}</Label>
          {readOnly ? (
            <div className="px-3 py-2 bg-muted rounded-md border text-sm">
              {initialValue?.name || ''}
            </div>
          ) : (
            <>
              <Input
                id="context-name"
                name="context-name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (errors.name && e.target.value.trim()) {
                    setErrors({ ...errors, name: undefined });
                  }
                }}
                placeholder="e.g., self-harm-v1, manipulation-v2"
                className={errors.name ? 'border-red-500' : ''}
              />
              {errors.name && (
                <p className="text-xs text-red-500">{errors.name}</p>
              )}
            </>
          )}
        </div>

        {/* Tools Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>{readOnly ? 'Available Tools' : 'Available Tools'}</Label>
            {!readOnly && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addTool}
                className="h-8"
              >
                <Plus className="h-3 w-3 mr-1" />
                Add Tool
              </Button>
            )}
          </div>

          {/* Tool List */}
          {tools.length > 0 && (
            <div className="space-y-3 mt-3">
              {tools.map((tool, index) => (
                <div
                  key={index}
                  className="p-3 rounded-md border bg-slate-50 dark:bg-slate-900/50"
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2">
                      <Settings className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium">
                        Tool {index + 1}
                      </span>
                    </div>
                    {!readOnly && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeTool(index)}
                        className="h-8 w-8 p-0 hover:bg-red-100 dark:hover:bg-red-900/20"
                      >
                        <Trash2 className="h-3 w-3 text-red-500" />
                      </Button>
                    )}
                  </div>

                  <div className="space-y-2">
                    <div>
                      <Label className="text-xs">Type</Label>
                      {readOnly ? (
                        <div className="px-2 py-1 bg-background/50 rounded text-xs">
                          function
                        </div>
                      ) : (
                        <>
                          <Select
                            value={tool.type}
                            onValueChange={(value: 'function') =>
                              updateTool(index, 'type', value)
                            }
                          >
                            <SelectTrigger className="h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="function">function</SelectItem>
                            </SelectContent>
                          </Select>
                          <p className="text-xs text-muted-foreground mt-1">
                            Takes a JSON schema as input to define parameters
                          </p>
                        </>
                      )}
                    </div>

                    <div>
                      <Label className="text-xs">Name</Label>
                      {readOnly ? (
                        <div className="px-2 py-1 bg-background/50 rounded text-xs font-mono">
                          {tool.name}
                        </div>
                      ) : (
                        <Input
                          value={tool.name}
                          onChange={(e) =>
                            updateTool(index, 'name', e.target.value)
                          }
                          placeholder="e.g., search_web, calculate"
                          className={cn(
                            'text-xs',
                            errors.tools?.[index] ? 'border-red-500' : ''
                          )}
                        />
                      )}
                    </div>

                    <div>
                      <Label className="text-xs">Description</Label>
                      {readOnly ? (
                        <div className="px-2 py-1 bg-background/50 rounded text-xs">
                          {tool.description}
                        </div>
                      ) : (
                        <Textarea
                          value={tool.description}
                          onChange={(e) =>
                            updateTool(index, 'description', e.target.value)
                          }
                          placeholder="Describe what this tool does..."
                          rows={2}
                          className={cn(
                            'resize-none text-xs',
                            errors.tools?.[index] ? 'border-red-500' : ''
                          )}
                        />
                      )}
                    </div>

                    {tool.type === 'function' && (
                      <div>
                        <Label className="text-xs">
                          Parameters (JSON Schema)
                        </Label>
                        {readOnly ? (
                          tool.parameters ? (
                            <div className="px-2 py-1 bg-background/50 rounded text-xs font-mono overflow-x-auto">
                              {JSON.stringify(tool.parameters, null, 2)}
                            </div>
                          ) : (
                            <div className="px-2 py-1 bg-background/50 rounded text-xs text-muted-foreground">
                              No parameters defined
                            </div>
                          )
                        ) : (
                          <JsonSchemaEditor
                            value={tool.parameters || createDefaultJsonSchema()}
                            onChange={(params) =>
                              updateToolParameters(index, params)
                            }
                            className={cn(
                              'text-xs',
                              errors.tools?.[index] ? 'border-red-500' : ''
                            )}
                          />
                        )}
                      </div>
                    )}
                  </div>

                  {errors.tools?.[index] && (
                    <p className="text-xs text-red-500 mt-1">
                      {errors.tools[index]}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {tools.length === 0 && (
            <div className="text-xs text-muted-foreground italic py-2">
              No tools configured. Tools allow the model to call functions
              during generation.
            </div>
          )}
        </div>

        {/* Messages Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label>{readOnly ? 'Messages' : 'Messages *'}</Label>
            {!readOnly && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addMessage}
                className="h-8"
              >
                <Plus className="h-3 w-3 mr-1" />
                Add Message
              </Button>
            )}
          </div>

          {/* Message List */}
          <div className="space-y-3 mt-3">
            {messages.map((message, index) => (
              <div
                key={index}
                className={cn(
                  'p-3 rounded-md transition-colors',
                  getRoleStyle(message.role)
                )}
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2">
                    {readOnly ? (
                      <>
                        <span
                          className={cn(
                            'text-xs px-2 py-1 rounded font-medium',
                            getRoleBadgeStyle(message.role)
                          )}
                        >
                          {message.role.charAt(0).toUpperCase() +
                            message.role.slice(1)}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          Message {index + 1}
                        </span>
                      </>
                    ) : (
                      <>
                        <Select
                          value={message.role}
                          onValueChange={(value) =>
                            updateMessage(index, 'role', value)
                          }
                        >
                          <SelectTrigger className="w-32 h-8">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="user">User</SelectItem>
                            <SelectItem value="assistant">Assistant</SelectItem>
                            <SelectItem value="system">System</SelectItem>
                            <SelectItem value="tool">Tool</SelectItem>
                          </SelectContent>
                        </Select>
                        <span
                          className={cn(
                            'text-xs px-2 py-1 rounded',
                            getRoleBadgeStyle(message.role)
                          )}
                        >
                          Message {index + 1}
                        </span>
                      </>
                    )}
                  </div>
                  {!readOnly && messages.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeMessage(index)}
                      className="h-8 w-8 p-0 hover:bg-red-100 dark:hover:bg-red-900/20"
                    >
                      <Trash2 className="h-3 w-3 text-red-500" />
                    </Button>
                  )}
                </div>
                {readOnly ? (
                  <div className="space-y-3">
                    <div className="text-sm whitespace-pre-wrap font-mono bg-background/50 p-2 rounded">
                      {message.content}
                    </div>
                    {message.role === 'assistant' &&
                      message.tool_calls &&
                      message.tool_calls.length > 0 && (
                        <div className="bg-secondary border border-border rounded-md p-3 space-y-3">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                              Tool Calls
                            </span>
                            <span className="text-xs text-muted-foreground">
                              ({message.tool_calls.length})
                            </span>
                          </div>
                          <div className="space-y-2">
                            {message.tool_calls.map(
                              (toolCall, toolCallIndex) => (
                                <div
                                  key={
                                    toolCall.id || `${index}-${toolCallIndex}`
                                  }
                                  className="bg-background rounded-md border border-border/50 p-3 space-y-2"
                                >
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="flex items-center gap-2">
                                      <div className="text-sm font-medium text-primary">
                                        {toolCall.function || 'Unnamed tool'}
                                      </div>
                                      <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-blue-bg text-blue-text border border-blue-border">
                                        {toolCall.type}
                                      </span>
                                    </div>
                                    {toolCall.id && (
                                      <div className="text-xs font-mono text-muted-foreground">
                                        ID: {toolCall.id}
                                      </div>
                                    )}
                                  </div>
                                  {toolCall.arguments !== undefined &&
                                    toolCall.arguments !== null && (
                                      <div className="space-y-1">
                                        <div className="text-xs text-muted-foreground uppercase tracking-wide">
                                          Arguments
                                        </div>
                                        <pre className="text-xs font-mono bg-secondary rounded p-2 whitespace-pre-wrap break-words">
                                          {formatToolData(toolCall)}
                                        </pre>
                                      </div>
                                    )}
                                  {toolCall.view?.content && (
                                    <div className="space-y-1">
                                      <div className="text-xs text-muted-foreground uppercase tracking-wide">
                                        View
                                      </div>
                                      <div className="text-xs font-mono bg-secondary rounded p-2 whitespace-pre-wrap break-words">
                                        {toolCall.view.content}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              )
                            )}
                          </div>
                        </div>
                      )}
                  </div>
                ) : (
                  <>
                    <Textarea
                      value={message.content}
                      onChange={(e) =>
                        updateMessage(index, 'content', e.target.value)
                      }
                      placeholder={`Enter ${message.role} message...`}
                      rows={4}
                      className={cn(
                        'resize-none font-mono text-xs',
                        errors.messages?.[index] ? 'border-red-500' : ''
                      )}
                    />

                    {message.role === 'tool' && (
                      <div className="mt-2">
                        <Label className="text-xs">Tool Call ID</Label>
                        <Input
                          value={message.tool_call_id || ''}
                          onChange={(e) =>
                            updateMessage(index, 'tool_call_id', e.target.value)
                          }
                          placeholder="Enter tool call ID this message responds to..."
                          className="text-xs mt-1"
                        />
                      </div>
                    )}

                    {message.role === 'assistant' && (
                      <div className="mt-2 space-y-2">
                        <div className="flex items-center justify-between">
                          <Label className="text-xs">Tool Calls</Label>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => addToolCall(index)}
                            className="text-xs h-6"
                          >
                            <Plus className="h-3 w-3 mr-1" />
                            Add Tool Call
                          </Button>
                        </div>

                        {message.tool_calls &&
                          message.tool_calls.length > 0 && (
                            <div className="space-y-2">
                              {message.tool_calls.map(
                                (toolCall, toolCallIndex) => (
                                  <div
                                    key={toolCallIndex}
                                    className="border rounded p-2 space-y-2 bg-slate-50 dark:bg-slate-900/50"
                                  >
                                    <div className="flex items-center gap-2">
                                      <Select
                                        value={toolCall.type || 'function'}
                                        onValueChange={(value: 'function') =>
                                          updateToolCall(index, toolCallIndex, {
                                            type: value,
                                          })
                                        }
                                      >
                                        <SelectTrigger className="w-28 h-6 text-xs">
                                          <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                          <SelectItem value="function">
                                            Function
                                          </SelectItem>
                                        </SelectContent>
                                      </Select>
                                      <Input
                                        value={toolCall.id}
                                        onChange={(e) =>
                                          updateToolCall(index, toolCallIndex, {
                                            id: e.target.value,
                                          })
                                        }
                                        placeholder="Tool call ID"
                                        className="flex-1 text-xs h-6"
                                      />
                                      <Input
                                        value={toolCall.function}
                                        onChange={(e) =>
                                          updateToolCall(index, toolCallIndex, {
                                            function: e.target.value,
                                          })
                                        }
                                        placeholder="Tool name"
                                        className="flex-1 text-xs h-6"
                                      />
                                      <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={() =>
                                          removeToolCall(index, toolCallIndex)
                                        }
                                        className="h-6 w-6 p-0"
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </Button>
                                    </div>
                                    <div>
                                      <Label className="text-xs">
                                        Arguments (JSON)
                                      </Label>
                                      <Textarea
                                        value={
                                          typeof toolCall.arguments === 'string'
                                            ? toolCall.arguments
                                            : toolCall.arguments
                                              ? JSON.stringify(
                                                  toolCall.arguments,
                                                  null,
                                                  2
                                                )
                                              : '{}'
                                        }
                                        onChange={(e) => {
                                          updateToolCall(index, toolCallIndex, {
                                            arguments: e.target.value,
                                          });
                                        }}
                                        placeholder='Enter tool arguments as JSON (e.g., {"key": "value"})'
                                        className={cn(
                                          'text-xs font-mono min-h-[60px] mt-1',
                                          errors.toolCalls?.[index]?.[
                                            toolCallIndex
                                          ]
                                            ? 'border-red-500'
                                            : ''
                                        )}
                                        rows={3}
                                      />
                                      {errors.toolCalls?.[index]?.[
                                        toolCallIndex
                                      ] && (
                                        <p className="text-xs text-red-500 mt-1">
                                          {
                                            errors.toolCalls[index][
                                              toolCallIndex
                                            ]
                                          }
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                )
                              )}
                            </div>
                          )}
                      </div>
                    )}

                    {errors.messages?.[index] && message.role !== 'tool' && (
                      <p className="text-xs text-red-500 mt-1">
                        {errors.messages[index]}
                      </p>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer Actions */}
      {readOnly ? (
        <div className="flex justify-between pt-3 border-t">
          {onDelete && (
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(true)}
              className="text-red-text hover:bg-red-muted"
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          )}
          <div className="flex gap-2 ml-auto">
            <Button variant="outline" onClick={handleClose}>
              Close
            </Button>
            {onFork && (
              <Button onClick={handleFork}>
                <Copy className="h-4 w-4 mr-2" />
                Clone Base Context
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="flex justify-end gap-2 pt-3 border-t">
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button onClick={handleSave}>
            {initialValue ? 'Save Changes' : 'Create Base Context'}
          </Button>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {readOnly && onDelete && (
        <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete Base Context</DialogTitle>
              <DialogDescription className="space-y-2">
                <p>
                  Are you sure you want to delete &quot;{initialValue?.name}
                  &quot;?
                </p>
                <p className="text-sm text-muted-foreground">
                  Note: This base context will be hidden from the list but may
                  still be visible in experiments that depend on it. The data
                  will not be permanently deleted to preserve experiment
                  history.
                </p>
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowDeleteDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={() => {
                  onDelete();
                  setShowDeleteDialog(false);
                }}
                className="bg-red-bg text-red-text hover:bg-red-muted"
              >
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

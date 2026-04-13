/**
 * Chat History Intelligence Pipeline — orchestrator.
 *
 * Chains 4 phases:
 *   1. Extraction — per-conversation LLM analysis
 *   2. Clustering — group conversations into projects
 *   3. Agent Mapping — score and recommend agents
 *   4. Server Operations — create folders, move chats, create agents
 */

import type {
  Agent,
  AgentContext,
  FolderModel,
  ProjectCluster,
} from '@/constants/types';
import { extractConversations } from '@/services/pipeline/extraction';
import { clusterIntoProjects, type ClusteringResult } from '@/services/pipeline/clustering';
import { mapProjectsToAgents } from '@/services/pipeline/agentMapping';
import { createAgentsFromRecommendations } from '@/services/agentFactory';
import {
  createFolder,
  listFolders,
  moveChatToFolder,
  listAgentModels,
  getModels,
} from '@/services/api';
import { agentFromServerModel } from '@/services/agentMapper';

// ── Types ──────────────────────────────────────────────────────

export interface PipelineProgress {
  phase: number;       // 1-4
  phaseName: string;
  detail: string;
  percent: number;     // 0-100
}

export interface PipelineResult {
  projects: ProjectCluster[];
  agentsCreated: Agent[];
  agentsFailed: string[];
  foldersCreated: FolderModel[];
  chatsMoved: number;
  standalone: Array<{ conversation_id: string; title: string; reason: string }>;
  userProfile: ClusteringResult['userProfile'];
}

// ── Phase 4: Server Operations ─────────────────────────────────

async function createProjectFolders(
  projects: ProjectCluster[],
): Promise<Map<string, FolderModel>> {
  // Get existing folders to avoid duplicates
  const existing = await listFolders();
  const existingNames = new Set(existing.map((f) => f.name.toLowerCase()));

  const folderMap = new Map<string, FolderModel>();

  for (const project of projects) {
    if (existingNames.has(project.project_name.toLowerCase())) {
      // Find the existing folder and map it
      const match = existing.find(
        (f) => f.name.toLowerCase() === project.project_name.toLowerCase(),
      );
      if (match) {
        folderMap.set(project.project_id, match);
      }
      continue;
    }

    try {
      const folder = await createFolder({
        name: project.project_name,
        meta: {
          description: project.project_description,
          primary_domain: project.primary_domain,
          status: project.status,
        },
      });
      folderMap.set(project.project_id, folder);
    } catch (err) {
      console.warn(`Failed to create folder for ${project.project_name}:`, err);
    }
  }

  return folderMap;
}

async function organizeChats(
  projects: ProjectCluster[],
  folderMap: Map<string, FolderModel>,
): Promise<number> {
  let moved = 0;

  for (const project of projects) {
    const folder = folderMap.get(project.project_id);
    if (!folder) continue;

    for (const chatId of project.conversation_ids) {
      try {
        await moveChatToFolder(chatId, folder.id);
        moved++;
      } catch {
        // Chat may not exist or already be in a folder
      }
    }
  }

  return moved;
}

// ── Main Pipeline ──────────────────────────────────────────────

/**
 * Run the full Chat History Intelligence Pipeline.
 *
 * @param onProgress — called at each step with phase info and percentage
 * @param context — optional user context for agent personalization
 */
export async function runPipeline(
  onProgress: (progress: PipelineProgress) => void,
  context?: AgentContext,
): Promise<PipelineResult> {
  // ── Phase 1: Extraction ────────────────────────────────────
  onProgress({
    phase: 1,
    phaseName: 'Analyzing Conversations',
    detail: 'Reading your chat history...',
    percent: 0,
  });

  const extractions = await extractConversations((current, total) => {
    const pct = Math.round((current / Math.max(total, 1)) * 100);
    onProgress({
      phase: 1,
      phaseName: 'Analyzing Conversations',
      detail: `Analyzed ${current} of ${total} chats...`,
      percent: pct,
    });
  });

  if (extractions.length === 0) {
    return {
      projects: [],
      agentsCreated: [],
      agentsFailed: [],
      foldersCreated: [],
      chatsMoved: 0,
      standalone: [],
      userProfile: {
        primary_roles: [],
        top_skills: [],
        work_style: 'systematic',
        tool_ecosystem: 'mixed',
        recurring_needs: [],
        growth_areas: [],
      },
    };
  }

  // ── Phase 2: Clustering ────────────────────────────────────
  onProgress({
    phase: 2,
    phaseName: 'Discovering Projects',
    detail: `Clustering ${extractions.length} conversations into projects...`,
    percent: 0,
  });

  const clusterResult = await clusterIntoProjects(extractions);

  onProgress({
    phase: 2,
    phaseName: 'Discovering Projects',
    detail: `Found ${clusterResult.projects.length} projects`,
    percent: 100,
  });

  // ── Phase 3: Agent Mapping ─────────────────────────────────
  onProgress({
    phase: 3,
    phaseName: 'Mapping Agents',
    detail: 'Scoring agent recommendations...',
    percent: 0,
  });

  // Get existing agents for dedup
  const [{ items: existingModels }, baseModels] = await Promise.all([
    listAgentModels(),
    getModels(),
  ]);
  const existingAgents = existingModels.map((m) =>
    agentFromServerModel(m, baseModels),
  );

  const recommendations = mapProjectsToAgents(
    clusterResult.projects,
    existingAgents,
  );

  onProgress({
    phase: 3,
    phaseName: 'Mapping Agents',
    detail: `Recommending ${recommendations.length} agents`,
    percent: 100,
  });

  // ── Phase 4: Server Operations ─────────────────────────────
  onProgress({
    phase: 4,
    phaseName: 'Setting Up Workspace',
    detail: 'Creating project folders...',
    percent: 0,
  });

  // Create folders
  const folderMap = await createProjectFolders(clusterResult.projects);
  const foldersCreated = Array.from(folderMap.values());

  onProgress({
    phase: 4,
    phaseName: 'Setting Up Workspace',
    detail: `Created ${foldersCreated.length} folders. Moving chats...`,
    percent: 30,
  });

  // Move chats into folders
  const chatsMoved = await organizeChats(clusterResult.projects, folderMap);

  onProgress({
    phase: 4,
    phaseName: 'Setting Up Workspace',
    detail: `Moved ${chatsMoved} chats. Creating agents...`,
    percent: 60,
  });

  // Create recommended agents
  const { created: agentsCreated, failed: agentsFailed } =
    await createAgentsFromRecommendations(
      recommendations,
      context,
      (current, total, name) => {
        const pct = 60 + Math.round((current / Math.max(total, 1)) * 40);
        onProgress({
          phase: 4,
          phaseName: 'Setting Up Workspace',
          detail: `Creating ${name}...`,
          percent: pct,
        });
      },
    );

  onProgress({
    phase: 4,
    phaseName: 'Setting Up Workspace',
    detail: 'Done!',
    percent: 100,
  });

  return {
    projects: clusterResult.projects,
    agentsCreated,
    agentsFailed,
    foldersCreated,
    chatsMoved,
    standalone: clusterResult.standalone,
    userProfile: clusterResult.userProfile,
  };
}

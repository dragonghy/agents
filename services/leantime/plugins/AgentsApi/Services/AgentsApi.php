<?php

namespace Leantime\Plugins\AgentsApi\Services;

use Leantime\Domain\Comments\Repositories\Comments as CommentRepository;
use Leantime\Domain\Projects\Repositories\Projects as ProjectRepository;

/**
 * AgentsApi plugin — extends Leantime JSON-RPC with agent-platform operations.
 *
 * Methods are auto-discovered by Leantime's reflection-based RPC handler.
 * Call via: leantime.rpc.AgentsApi.<method>
 */
class AgentsApi
{
    private ProjectRepository $projectRepository;
    private CommentRepository $commentRepository;

    public function __construct(
        ProjectRepository $projectRepository,
        CommentRepository $commentRepository
    ) {
        $this->projectRepository = $projectRepository;
        $this->commentRepository = $commentRepository;
    }

    /**
     * Delete a project and all its associated data.
     *
     * @param int $id The project ID to delete.
     * @return bool
     *
     * @api
     */
    public function deleteProject(int $id): bool
    {
        $this->projectRepository->deleteProject($id);
        $this->projectRepository->deleteAllUserRelations($id);
        return true;
    }

    /**
     * Add a comment to a module entity (ticket, project, etc.).
     *
     * Bypasses the built-in Comments service notification system which
     * crashes in JSON-RPC context due to missing session('currentProject')
     * and entity array/object type mismatch.
     *
     * @param string $text    The comment text.
     * @param string $module  The module name (e.g. "ticket").
     * @param int    $entityId The entity ID (e.g. ticket ID).
     * @return string|false   The new comment ID, or false on failure.
     *
     * @api
     */
    public function addComment(string $text, string $module, int $entityId): string|false
    {
        // Normalize module name: "tickets" -> "ticket"
        if ($module === 'tickets') {
            $module = 'ticket';
        }

        $values = [
            'text' => $text,
            'date' => date('Y-m-d H:i:s'),
            'userId' => session('userdata.id') ?? 1,
            'moduleId' => $entityId,
            'commentParent' => 0,
            'status' => '',
        ];

        return $this->commentRepository->addComment($values, $module);
    }
}

"""
DRF views for the campaigns admin surface.

Endpoints:
  GET POST                    /api/admin/segments/
  GET PATCH DELETE            /api/admin/segments/{id}/
  GET                         /api/admin/segments/{id}/preview/?limit=20
  GET POST                    /api/admin/campaigns/
  GET PATCH DELETE            /api/admin/campaigns/{id}/
  POST                        /api/admin/campaigns/{id}/send/
  POST                        /api/admin/campaigns/{id}/cancel/
  GET                         /api/admin/campaigns/{id}/runs/?status=&page=

State-machine enforcement (re-send, edit-after-send) lives in
`campaigns.runner` — these views just translate exceptions to HTTP codes.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from campaigns.models import Campaign, CampaignRun, CampaignStatus, Segment
from campaigns.runner import (
    CampaignAlreadyProcessed,
    CampaignTooLarge,
    cancel_campaign,
    send_campaign,
)
from campaigns.segments import customers_for

from .serializers_campaigns import (
    CampaignRunSerializer,
    CampaignSerializer,
    SegmentSerializer,
)

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class RunsPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AdminPagination(PageNumberPagination):
    """Default pagination for list endpoints. Wraps results in `{count,
    next, previous, results}` so the frontend can rely on a stable shape
    even when no `page` param is sent."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


class SegmentListCreateView(ListCreateAPIView):
    """GET/POST /api/admin/segments/"""

    serializer_class = SegmentSerializer
    pagination_class = AdminPagination

    def get_queryset(self):
        qs = Segment.objects.select_related("store", "created_by").all()
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)


class SegmentDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/admin/segments/{id}/"""

    serializer_class = SegmentSerializer
    queryset = Segment.objects.select_related("store", "created_by").all()


class SegmentPreviewView(APIView):
    """GET /api/admin/segments/{id}/preview/?limit=20"""

    def get(self, request, pk: int):
        try:
            segment = Segment.objects.get(pk=pk)
        except Segment.DoesNotExist:
            return Response({"detail": "Segment not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            limit = int(request.query_params.get("limit", "20"))
        except ValueError:
            limit = 20
        limit = max(1, min(limit, 100))

        qs = customers_for(segment)
        count = qs.count()
        sample = list(
            qs.values("id", "name", "phone", "tags", "total_visits", "last_visit_at")[:limit]
        )
        return Response({"count": count, "sample": sample})


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class CampaignListCreateView(ListCreateAPIView):
    """GET/POST /api/admin/campaigns/"""

    serializer_class = CampaignSerializer
    pagination_class = AdminPagination

    def get_queryset(self):
        qs = Campaign.objects.select_related("store", "segment", "created_by", "sent_by").all()
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)


class CampaignDetailView(RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/admin/campaigns/{id}/.

    PATCH refused with 409 once status leaves `draft`.
    """

    serializer_class = CampaignSerializer
    queryset = Campaign.objects.select_related("store", "segment", "created_by", "sent_by").all()

    def update(self, request, *args, **kwargs):
        campaign = self.get_object()
        if campaign.status != CampaignStatus.DRAFT:
            return Response({"error": "campaign_already_sent"}, status=status.HTTP_409_CONFLICT)
        return super().update(request, *args, **kwargs)


class CampaignSendView(APIView):
    """POST /api/admin/campaigns/{id}/send/ — requires {"confirm": true}."""

    def post(self, request, pk: int):
        if request.data.get("confirm") is not True:
            return Response({"error": "confirmation_required"}, status=status.HTTP_400_BAD_REQUEST)
        user = request.user if request.user.is_authenticated else None
        try:
            summary = send_campaign(pk, sent_by=user)
        except Campaign.DoesNotExist:
            return Response({"detail": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        except CampaignAlreadyProcessed:
            return Response({"error": "campaign_already_sent"}, status=status.HTTP_409_CONFLICT)
        except CampaignTooLarge as exc:
            return Response(
                {"error": "campaign_too_large", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(summary)


class CampaignCancelView(APIView):
    """POST /api/admin/campaigns/{id}/cancel/"""

    def post(self, request, pk: int):
        try:
            campaign = cancel_campaign(pk)
        except Campaign.DoesNotExist:
            return Response({"detail": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        except CampaignAlreadyProcessed:
            return Response({"error": "campaign_already_sent"}, status=status.HTTP_409_CONFLICT)
        return Response(CampaignSerializer(campaign).data)


class CampaignRunsListView(APIView):
    """GET /api/admin/campaigns/{id}/runs/?status=&page="""

    def get(self, request, pk: int):
        if not Campaign.objects.filter(pk=pk).exists():
            return Response({"detail": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)
        qs = CampaignRun.objects.filter(campaign_id=pk).select_related("customer").order_by("id")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = RunsPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        ser = CampaignRunSerializer(page, many=True)
        return paginator.get_paginated_response(ser.data)
